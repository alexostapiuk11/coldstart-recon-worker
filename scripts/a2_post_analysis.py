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
    engine_occupancy,
    host_speed_table,
    per_worker_concurrency,
    stall_breakdown,
    stall_share,
)
from autoscale.coldstart_ecdf import load_measured_lags
from autoscale.frontier import (
    COMPARED_SIGNALS,
    COST_TIE_RELATIVE_TOLERANCE,
    gap_at_iso_cost,
    h3_verdict,
    iso_cost_budget,
    pareto_frontier,
)
from autoscale.measured_curve import load_measured_curve
from autoscale.money_a2 import (
    Assumptions,
    dollars_per_day,
    dollars_per_million_requests,
    dollars_per_spike,
)
from autoscale.validation import (
    BIN_SECONDS,
    MAX_SEND_JITTER_SECONDS,
    EngineRun,
    engine_trajectories,
    validate_engine_arrivals,
)

A2 = Path("data/a2")
# Anchored at REPO like every input is: a bare relative default would write wherever the
# script happened to be launched from, and the test that compares the committed file
# would then compare nothing.
OUT = REPO / A2 / "post-analysis.json"
ATTEMPTS = {"engine": A2 / "validation-engine", "calibrated": A2 / "validation-calibrated"}
ONE_REPLICA = A2 / "validation"
PROBES = A2 / "lb-probes"
EXPLORATORY = A2 / "exploratory"
SWEEP = A2 / "frontier-sweep.json"
# The store every sweep's cold-start samples came from (a2_render_figures' --store default).
CAMPAIGN = Path("data/campaign.jsonl")
SENSITIVITY = EXPLORATORY / "sensitivity-service-speed.json"
CURVE = A2 / "service-curve.json"
GPU_RATE = A2 / "gpu-rate.json"
# Illustrative: one spike an hour. The post says so wherever it multiplies by it.
SPIKES_PER_DAY = 24.0
HOST_LEVELS = (32, 64, 128)
HEADLINE = ("arm A", "arm C", "ramp arm A", "ramp arm C")
STEP_RAMP = {"arm A": ("arm A", "ramp arm A"), "arm C": ("arm C", "ramp arm C")}
# Probes 1-3 ran two workers; 1 shows the per-worker cap, 2 and 3 the fill-first routing.
CONCURRENCY_PROBES = ("1", "2", "3")
RETURN_LEG_S = 0.1
STALL_THRESHOLD_S = 2.0
# A request over STALL_THRESHOLD_S client-side whose server latency is over this spent most
# of its delay inside the engine (the engine's own unloaded p50 is about 0.3 s).
SERVER_BACKLOG_S = 1.5
# The validation engine's --max-num-seqs (amendment 2026-10-04, second): what it runs at
# once. Requests past it queue inside the engine, which is what the in-flight count shows.
VALIDATION_ENGINE_CAP = 128
# Engine in-flight band around 100, for attempt 1's host against the re-measured host.
IN_FLIGHT_BAND = (90, 110)
# A load-balancer 502 that fails within this is "fast"; the 37 first attempts fall either
# well under it (at most 0.40 s) or well over it (at least 2.50 s), so the split does not
# depend on where inside that empty interval it is drawn.
FAST_502_S = 1.0
# Every store whose records name the host a worker ran on: the curve, the host
# re-measurement, and the three sets of validation repeats (void ones included).
HOST_RECORD_SOURCES = ("service-sweep", "exploratory", "validation", "validation-engine",
                       "validation-calibrated")
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


def _only(items, what: str, consequence: str):
    """The one element of `items`, or a refusal that names what was found and what breaks.

    Rejected: `(x,) = items`, whose "too many values to unpack" names neither the
    evidence nor the number that would have been mislabelled.
    """
    items = list(items)
    if len(items) != 1:
        raise SystemExit(f"expected exactly one of {what}, found {len(items)} ({items!r}); "
                         f"{consequence}")
    return items[0]


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
            "definition": f"per judged bin with an ok p50 on both sides in all {len(pairs)} repeats: "
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
        void_detail = []
        for v in voids:
            rec = _read_gz_json(d / v.name)
            ok = [t for t, st in zip(rec["server_received_s"], rec["status"], strict=True)
                  if st == 200]
            void_detail.append({"repeat": rec["repeat"], "responses_200": len(ok),
                                "responses_200_without_engine_arrival":
                                    sum(1 for t in ok if t is None)})
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
        raw = [y for repeat in residuals for _, y in repeat if y is not None]
        occupancy = []
        for record in records:
            counts = [n for _, n, _ in engine_occupancy(record)]
            occupancy.append({"repeat": record["repeat"], "arrivals": len(counts),
                              "share_of_arrivals_over_cap":
                                  sum(1 for n in counts if n > VALIDATION_ENGINE_CAP) / len(counts),
                              "max_in_flight": max(counts)})
        out[name] = {
            "outcome": verdict["outcome"], "detail": verdict["detail"],
            "compared": verdict["compared"], "misses": verdict["misses"],
            "agreeing": verdict["agreeing"], "max_miss_seconds": verdict["max_miss_seconds"],
            "max_miss_is_censoring": verdict["max_miss_is_censoring"],
            "void_repeats": len(voids),
            "void_repeat_detail": void_detail,
            "engine_in_flight": {
                "cap": VALIDATION_ENGINE_CAP, "per_repeat": occupancy,
                "definition": "each stamped 200 occupies the engine over [server_received_s, "
                              "server_received_s + server_latency_s]; at each arrival, the "
                              "requests in flight on the engine, the arriving one included "
                              "(autoscale.a2_evidence.engine_occupancy); share of arrivals "
                              "with more than cap in flight, and the most in flight"},
            "residual_min_s": min(raw), "residual_max_s": max(raw),
            "typical_residual": _typical_residual(result.bins, pairs),
            "per_repeat": per_repeat,
            "residuals": residuals,
            "residuals_definition": f"per repeat, [bin start s, real p50 - predicted p50 s or "
                                    f"null unless both sides ok], {BIN_SECONDS:g} s bins by "
                                    "engine arrival",
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
    seen: dict[str, set] = {}  # raw worker ids per probe; only their counts leave this function
    probe2_502: list[float] = []
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
        seen[n] = set(labels)
        steps = {}
        for rate, stats in summary["steps"].items():
            unlabelled = sorted(set(stats["worker_share"]) - set(labels))
            if unlabelled:
                raise SystemExit(
                    f"probe {n} step {rate}: worker_share names {len(unlabelled)} worker(s) "
                    "that no row's x-a2-worker header or the summary's worker list carries, "
                    "so they cannot be given a 'worker N' label and the share table would "
                    "either drop them or publish their raw ids")
            step = {k: v for k, v in stats.items() if k != "worker_share"}
            step["worker_share"] = {labels[w]: s for w, s in stats["worker_share"].items()}
            step["delivered_rate_rps"] = delivered_rate(rows[rate])
            if n in CONCURRENCY_PROBES:
                step["per_worker_concurrency"] = {
                    labels[w]: c for w, c in
                    per_worker_concurrency(rows[rate], return_leg_s=RETURN_LEG_S).items()}
            got = [s for s in (_first_attempt_s(r) for r in rows[rate]) if s is not None]
            if n == "2":
                # Probe 2 did not retry: a load-balancer 502 is the row itself, with no
                # worker header, and its latency is how long it took to fail.
                probe2_502.extend(r["latency"] for r in rows[rate]
                                  if r.get("status") == LB_RETRY_STATUS
                                  and WORKER not in (r.get("headers") or {}))
            if got:
                retries.setdefault(n, {})[rate] = got
            steps[rate] = step
        probes[n] = {"status": summary["status"], "workers": len(labels), "steps": steps}
    for n, workers in seen.items():
        others = set().union(*(w for m, w in seen.items() if m != n))
        probes[n]["workers_seen_in_other_probes"] = len(workers & others)

    stall = []
    for path in sorted((REPO / ONE_REPLICA).glob("repeat-*.json.gz")):
        rel = ONE_REPLICA / path.name
        inputs.append(rel)
        rec = _read_gz_json(rel)
        ok = sum(1 for x, st in zip(rec["client_latency_s"], rec["status"], strict=True)
                 if x is not None and st == 200)
        split = stall_breakdown(rec, threshold_s=STALL_THRESHOLD_S,
                                server_backlog_s=SERVER_BACKLOG_S)
        statuses: dict[str, int] = {}
        for st in rec["status"]:
            if st != 200:
                statuses[str(st)] = statuses.get(str(st), 0) + 1
        stall.append({"repeat": rec["repeat"], "completed": ok, "void": rec["void"],
                      "share_over_threshold": stall_share(rec, threshold_s=STALL_THRESHOLD_S),
                      "share_client_minus_server_over_threshold":
                          split["share_client_minus_server_over"],
                      "share_of_over_threshold_with_server_over":
                          split["share_of_slow_with_server_over"],
                      "non_200_status": statuses,
                      "max_send_jitter_s": rec["max_jitter_s"],
                      "refused_for_send_jitter": rec["max_jitter_s"] > MAX_SEND_JITTER_SECONDS})

    every = sorted(s for steps in retries.values() for got in steps.values() for s in got)

    def _spread(xs: list[float]) -> dict:
        return {"count": len(xs), "min": min(xs) if xs else None, "max": max(xs) if xs else None}

    return {
        "probes": probes,
        "per_worker_concurrency_return_leg_s": RETURN_LEG_S,
        "per_worker_concurrency_note": "server intervals reconstructed: each ends return_leg_s "
                                       "before the client saw the response and lasts the "
                                       "stamped server latency (autoscale.a2_evidence)",
        "probes_1_to_3_distinct_workers": len(set().union(*(seen[n] for n in CONCURRENCY_PROBES))),
        "probes_1_to_3_distinct_workers_note": "x-a2-worker ids across the steps and summary of "
                                               "probes 1, 2 and 3, counted; the ids are not "
                                               "published",
        "stall_share": {"threshold_s": STALL_THRESHOLD_S,
                        "server_backlog_s": SERVER_BACKLOG_S,
                        "send_jitter_limit_s": MAX_SEND_JITTER_SECONDS,
                        "source": str(ONE_REPLICA) + " (one-replica repeats, client latency)",
                        "definition": "share_over_threshold: completed requests over threshold_s "
                                      "client-side; share_client_minus_server_over_threshold: "
                                      "client minus server latency over threshold_s (time "
                                      "outside the engine); share_of_over_threshold_with_server_"
                                      "over: of the requests over threshold_s client-side, those "
                                      "whose server latency is over server_backlog_s (time "
                                      "inside the engine)",
                        "repeats": stall},
        "lb_502_first_attempt_s": {
            "probes": retries,
            "count": len(every),
            "min": every[0] if every else None,
            "median": statistics.median(every) if every else None,
            "max": every[-1] if every else None,
            "fast_threshold_s": FAST_502_S,
            "fast": _spread([s for s in every if s <= FAST_502_S]),
            "slow": _spread([s for s in every if s > FAST_502_S]),
            "source": f"the {RETRY_MARK} header value '502:<seconds>' on rows of probes "
                      + ", ".join(sorted(retries)),
        },
        "probe2_502_s": {**_spread(sorted(probe2_502)),
                         "source": "probe 2's rows with status 502 and no x-a2-worker header "
                                   "(probe 2 did not retry them); their client latency"},
        "lb_502_first_attempt_validation_s": None,
        "lb_502_first_attempt_validation_s_why":
            "the validation records keep only the indices of retried requests "
            "(lb_502_retried), not the retry header's value, so the first attempt's "
            "duration was not recorded for any validation repeat",
    }


# --- host speed -----------------------------------------------------------------------


def _hosts_in_records(inputs: list) -> dict[str, set]:
    """Host ids per HOST_RECORD_SOURCES entry, read from every record that names one."""
    hosts: dict[str, set] = {}
    for line in (REPO / A2 / "service-sweep.jsonl").read_text().splitlines():
        hosts.setdefault("service-sweep", set()).add(json.loads(line)["host"]["host_id"])
    for setting in ("maxseqs128", "maxseqs256"):
        for line in (REPO / EXPLORATORY / f"{setting}.jsonl").read_text().splitlines():
            hosts.setdefault("exploratory", set()).add(json.loads(line)["host"]["host_id"])
    for name in ("validation", "validation-engine", "validation-calibrated"):
        for path in sorted((REPO / A2 / name).glob("repeat-*.json.gz")):  # void ones too
            inputs.append(A2 / name / path.name)
            hosts.setdefault(name, set()).update(_read_gz_json(A2 / name / path.name)["host_ids"])
    if set(hosts) != set(HOST_RECORD_SOURCES):
        raise SystemExit(f"host sources {sorted(hosts)} are not {sorted(HOST_RECORD_SOURCES)}; "
                         "the post's host count would cover a different set of records")
    return hosts


def _interpolate(points: dict[int, float], at: float) -> float:
    """Linear interpolation between the two measured levels that bracket `at`."""
    levels = sorted(points)
    lo = max(lv for lv in levels if lv <= at)
    hi = min(lv for lv in levels if lv >= at)
    if lo == hi:
        return points[lo]
    return points[lo] + (points[hi] - points[lo]) * (at - lo) / (hi - lo)


def _attempt1_at_band(latency: dict, maxseqs128: dict) -> dict:
    """Attempt 1's host at about 100 in flight, against the re-measured host and the curve.

    Attempt 1's host was never measured closed-loop. Its records still show its speed at
    one load: pooled over the three repeats, the median server latency of the requests that
    arrived with IN_FLIGHT_BAND in flight on the engine (the engine_occupancy count). The
    references are linearly interpolated to the band's middle between their measured levels.
    Rejected: a mean in-flight from Little's law, which is not a count at any arrival.
    """
    lats, hosts = [], set()
    lo, hi = IN_FLIGHT_BAND
    for k in (1, 2, 3):
        rec = _read_gz_json(ATTEMPTS["engine"] / f"repeat-{k}.json.gz")
        hosts.update(rec["host_ids"])
        lats.extend(lat for _, n, lat in engine_occupancy(rec) if lo <= n <= hi)
    mid = (lo + hi) / 2
    return {
        "host": _only(hosts, "hosts of attempt 1's repeats",
                      "the latency would describe a mix of machines under one host id"),
        "band": [lo, hi], "requests": len(lats),
        "median_server_latency_s": statistics.median(lats),
        "maxseqs128_interpolated_s": _interpolate(maxseqs128, mid),
        "curve_interpolated_s": _interpolate(latency, mid),
        "definition": f"pooled over attempt 1's three repeats: median server latency of 200s "
                      f"that arrived with {lo}..{hi} in flight on the engine, the arriving one "
                      f"included; references are the curve's and the maxseqs128 host's median "
                      f"latencies, linearly interpolated to {mid:g} between measured levels",
    }




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
                if key[1] not in latency:
                    raise SystemExit(
                        f"{path}: a run at concurrency {key[1]} has no curve latency to "
                        "divide by; its host ratio would be undefined and the host-speed "
                        "table would silently lack that level")
                spread.setdefault(key, []).append(r["latency_s"] / latency[key[1]])
        tables[setting] = {
            host: {str(level): {**row, "ratio_min": min(spread[(host, level)]),
                                "ratio_max": max(spread[(host, level)])}
                   for level, row in levels.items()}
            for host, levels in host_speed_table(runs, latency).items()}
    versions = {json.loads(line)["engine"]["vllm_version"]
                for path in (store, EXPLORATORY / "maxseqs128.jsonl", EXPLORATORY / "maxseqs256.jsonl")
                for line in (REPO / path).read_text().splitlines()}
    engine_version = _only(versions, "vLLM versions in the curve and re-measurement stores",
                           "the post names one engine version for runs that recorded several")
    calibrated: dict[str, dict[str, list[float]]] = {}
    for k in (1, 2, 3):
        rec = _read_gz_json(ATTEMPTS["calibrated"] / f"repeat-{k}.json.gz")
        host = _only(rec["host_ids"], f"host ids of calibrated repeat {k}",
                     "its calibration ratios would be filed under the wrong host or none, and "
                     "the post's per-host ratio would describe a mix of machines")
        for level, entry in rec["calibration"]["levels"].items():
            calibrated.setdefault(host, {}).setdefault(level, []).append(entry["ratio"])
    hosts = _hosts_in_records(inputs)
    measured = (hosts["service-sweep"] | hosts["exploratory"] | set(calibrated))
    (only128,) = tables["maxseqs128"].values()
    return {
        "hosts_in_records": {
            "count": len(set().union(*hosts.values())),
            "per_source": {k: len(v) for k, v in sorted(hosts.items())},
            "measured_for_speed": len(measured),
            "definition": "distinct host ids across the curve's runs (service-sweep), the host "
                          "re-measurement (exploratory) and every validation repeat, void ones "
                          "included; measured_for_speed counts those with a closed-loop "
                          "latency: the curve's host, the re-measured host and the calibrated "
                          "attempt's host"},
        "engine_version": engine_version,
        "engine_version_source": f"engine.vllm_version of every record in {store} and "
                                 f"{EXPLORATORY}/maxseqs*.jsonl; the validation records carry none",
        "attempt1_at_100_in_flight": _attempt1_at_band(
            latency, {int(lv): row["median_s"] for lv, row in only128.items()}),
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
    missing = sorted(COMPARED_SIGNALS - set(by))
    if missing:
        raise SystemExit(f"a sweep has no points for signal(s) {missing}; its frontiers, "
                         "reached p99s and hypotheses would be computed over a different "
                         "set of signals than the ones the post names")
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
    refused = sorted(t for t in HEADLINE if "point" not in gaps[t])
    if refused:
        raise SystemExit(f"the gap of sweep(s) {refused} was refused (no 'point'); H3 on the "
                         "remaining sweeps would be a verdict about a different set of sweeps "
                         "under the same name, so it is not computed")
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


def _censoring_reading(*, min_util: float, highest_threshold: float, all_at_cap: bool) -> str:
    """The sentence that explains the censoring, written only if its premises hold.

    Rejected: a fixed sentence, which would go on saying "above every threshold"
    after a re-measured curve or a changed grid made it false.
    """
    if not min_util > highest_threshold:
        raise SystemExit(
            f"the curve's lowest GPU utilisation ({min_util:g}) is not above the highest "
            f"utilisation scale-up threshold ({highest_threshold:g}), so the utilisation "
            "controller would not scale up at every chance and the 'above every threshold' "
            "reading would be false; the censoring explanation must be rewritten, not "
            "emitted")
    tail = ("every utilisation run's cost equals the cap cost" if all_at_cap
            else "NOT every utilisation run's cost equals the cap cost (see per_sweep)")
    return (f"the curve's GPU utilisation is at least {min_util:g} at every measured level, "
            f"above the highest utilisation scale-up threshold ({highest_threshold:g}), so the "
            f"utilisation controller scales up at every chance; {tail}")


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
    highest = max(identity["thresholds"]["utilization"][0])
    return {
        "cap_cost_replica_s": cap,
        "cap_cost_definition": "one initial replica for the window plus one more at every "
                               "cooldown from the first evaluation (t = evaluate_every) up "
                               "to max_replicas, none removed: until + sum over k = 0.."
                               "max_replicas-2 of (until - evaluate_every - k * cooldown)",
        "max_replicas": identity["max_replicas"],
        "per_sweep": per,
        "curve_gpu_util_min_over_measured_levels": min(util_levels),
        "highest_utilization_scale_up_threshold": highest,
        "reading": _censoring_reading(
            min_util=min(util_levels), highest_threshold=highest,
            all_at_cap=all(s["every_utilization_run_at_cap_cost"] for s in per.values())),
    }


def _h2_noise(sources: dict, frontiers: dict, sweeps: dict, identity: dict) -> dict:
    """What H2's per-sweep verdicts rest on: how far apart the signals are against how far
    apart utilisation's own identical-fleet policies are.

    Every at-cap utilisation policy runs the same fleet, yet their median p99s differ,
    because `autoscale.sweep._derive_seed` keys a trace on (seed, scale_up_at,
    scale_down_at, repetition) and not on the signal: policies with different thresholds
    replay different arrival traces. That spread is therefore trace-to-trace noise, and a
    margin between signals smaller than it is not distinguishable from it. Rejected:
    quoting the margin alone, which makes a 43 ms lead look like a measurement.

    `iso_cost_slice_constrains_others` is computed: it is True if any queue-depth or
    in-flight frontier point costs more than the budget, i.e. the slice cuts off a point
    the others could have used. False means the slice binds on utilisation only.
    """
    cap = _cap_cost(identity)
    out = {}
    for tag in HEADLINE:
        at_cap = [p.p99 for p in sources[tag] if p.signal == "utilization" and all(
            math.isclose(c, cap, rel_tol=CAP_COST_RELATIVE_TOLERANCE) for c in p.cost_samples)]
        if not at_cap:
            raise SystemExit(f"{tag}: no utilisation policy is at the cap cost, so there is no "
                             "at-cap spread to compare the H2 margin against; the post would "
                             "state a margin with nothing to size it by")
        reached = {s: r["p99_s"] for s, r in sweeps[tag]["reached"].items()}
        others = {s: v for s, v in reached.items() if s != "utilization"}
        budget = sweeps[tag]["budget_replica_s"]
        other_costs = [p.cost for s in ("queue_depth", "in_flight_concurrency")
                       for p in frontiers[tag][s]]
        margin = reached["utilization"] - max(others.values())
        out[tag] = {
            "at_cap_policy_p99_s": {"count": len(at_cap), "min": min(at_cap),
                                    "median": statistics.median(at_cap), "max": max(at_cap)},
            "h2_margin_s": margin,
            "margin_vs_best_other_s": reached["utilization"] - min(others.values()),
            "tie_seconds": hyp.TIE_SECONDS,
            "margin_inside_at_cap_spread": abs(margin) < max(at_cap) - min(at_cap),
            "margin_vs_best_other_inside_at_cap_spread":
                abs(reached["utilization"] - min(others.values())) < max(at_cap) - min(at_cap),
            "iso_cost_slice_constrains_others": any(
                c > budget * (1 + COST_TIE_RELATIVE_TOLERANCE) for c in other_costs),
            "others_highest_frontier_cost_replica_s": max(other_costs),
            "budget_replica_s": budget,
        }
    return {
        "per_sweep": out,
        "_note": "at-cap utilisation policies run the same fleet (every run at the cap cost) "
                 "but differ in median p99 because autoscale.sweep._derive_seed seeds a trace "
                 "by (seed, scale_up_at, scale_down_at, repetition), not by signal, so "
                 "policies with different thresholds replay different traces",
        "h2_margin_definition": "utilisation's reached p99 minus the highest reached p99 of "
                                "the other two signals, signed; H2 holds exactly when it "
                                "exceeds tie_seconds",
        "margin_vs_best_other_definition": "utilisation's reached p99 minus the lowest "
                                           "reached p99 of the other two signals, signed",
    }


def _cold_start(inputs: list) -> dict:
    """The arms' measured scale-up lag, as the sweeps resampled it (repeat-host runs only).

    Read through `load_measured_lags`, the loader the sweeps used, so the median the
    figure's axis shows is the median of the samples the simulation drew from. Rejected:
    re-deriving the lag from the raw store, which would have to repeat that loader's
    first-touch exclusion and drift from it. The percentiles interpolate linearly
    (`statistics.quantiles(method="inclusive")` is numpy's default, as harness.stats uses).
    """
    inputs.append(CAMPAIGN)
    lags = load_measured_lags(REPO / CAMPAIGN)
    out = {}
    for arm in ("A", "C"):
        xs = sorted(lags[arm].samples)
        deciles = statistics.quantiles(xs, n=10, method="inclusive")
        out[arm] = {"median": statistics.median(xs), "p10": deciles[0], "p90": deciles[-1],
                    "n": len(xs)}
    return out


def _campaign_runs() -> int:
    """Records in artifact 1's store, every arm, before any exclusion."""
    return sum(1 for line in (REPO / CAMPAIGN).read_text().splitlines() if line.strip())


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
        "cold_start": _cold_start(inputs),
        "campaign_runs": _campaign_runs(),
        "campaign_runs_definition": f"records in {CAMPAIGN}, every arm, before any exclusion",
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
        "h2_noise": _h2_noise(sources, frontiers, sweeps, identity),
        "identity": {k: identity[k] for k in ("seed", "repetitions", "until", "max_replicas",
                                              "cooldown", "evaluate_every")},
    }


def money_section(lb: dict, sim: dict, inputs: list) -> dict:
    """Two money statements: the load balancer's default cap (measured throughput at the
    reported rate), the signal choice (UNVALIDATED).

    The rate is RunPod's reported `costPerHr` for one worker, read from
    data/a2/gpu-rate.json; the source string there names the endpoint and is not
    republished here (the file is the input). Rejected: a rate typed into this script,
    which would drift from the file the post's assumptions table cites.
    """
    inputs.append(GPU_RATE)
    rate = _read_json(GPU_RATE)
    if rate.get("provenance") != "reported":
        raise SystemExit(f"{GPU_RATE} is marked {rate.get('provenance')!r}, not 'reported'; "
                         "the post labels the rate as RunPod's reported costPerHr, and a "
                         "different provenance needs different words")
    a = Assumptions(gpu_hourly_rate=rate["gpu_hourly_rate"], spikes_per_day=SPIKES_PER_DAY)

    p1, p3 = lb["probes"]["1"], lb["probes"]["3"]
    workers = _only({p1["workers"], p3["workers"]}, "worker counts across probes 1 and 3",
                    "two workers are priced at both scaler values (a different pair in each "
                    "probe), so a different count would make the ratio compare fleets of "
                    "different sizes")
    ceiling = statistics.median(s["delivered_rate_rps"] for s in p1["steps"].values())
    at_300 = p3["steps"]["300"]["delivered_rate_rps"]

    def priced(delivered: float) -> dict:
        return {"delivered_rate_rps": delivered,
                "dollars_per_million": dollars_per_million_requests(
                    a, workers=workers, rate=delivered)}

    reached = sim["sweeps"]["arm A"]["reached"]
    p99s = [r["p99_s"] for r in reached.values()]
    spread = max(p99s) - min(p99s)
    return {
        "gpu": rate["gpu"],
        "gpu_hourly_rate": a.gpu_hourly_rate,
        "gpu_rate_provenance": a.provenance["gpu_hourly_rate"],
        "gpu_rate_caveat": rate["caveat"],
        "gpu_rate_source_file": str(GPU_RATE),
        "list_price_hourly": rate["list_price_hourly"],
        "list_price_source": rate["list_price_source"],
        "list_price_read_on": rate["list_price_read_on"],
        "list_over_reported": rate["list_price_hourly"] / a.gpu_hourly_rate,
        "list_over_reported_definition": "the pricing page's serverless rate over the reported "
                                         "costPerHr; every dollar figure scales by it",
        "spikes_per_day": a.spikes_per_day,
        "spikes_per_day_provenance": a.provenance["spikes_per_day"],
        "load_balancer_cap": {
            "workers": workers,
            "scaler_4": priced(ceiling),
            "scaler_4_source": "probe 1 (scaler value 4), median of its steps' delivered rates; "
                               "the 100 req/s step ended on client-side errors",
            "scaler_128": priced(at_300),
            "scaler_128_source": "probe 3 (scaler value 128), delivered rate at the 300 req/s step",
            "ratio": at_300 / ceiling,
            "ratio_definition": "scaler 128's delivered rate over scaler 4's, which is also "
                                "scaler 4's cost per request over scaler 128's (same workers, "
                                "same hourly rate)",
        },
        "signal_choice": {
            "label": "UNVALIDATED: simulator failed validation twice; "
                     f"p99s differ by {round(spread * 1000)} ms",
            "sweep": "arm A",
            "p99_spread_s": spread,
            "p99_spread_definition": "highest minus lowest reached p99 over the three signals "
                                     "on this sweep",
            "per_signal": {
                s: {"replica_seconds": r["cost_replica_s"],
                    "dollars_per_spike": dollars_per_spike(
                        a, replica_seconds=r["cost_replica_s"]),
                    "dollars_per_day": dollars_per_day(
                        a, replica_seconds_per_spike=r["cost_replica_s"])}
                for s, r in reached.items()},
        },
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
        "spend_why": "measured spend is not in the committed evidence; its keys are defined by "
                     "Task 13 of the publication plan, which has not landed",
    }
    analysis["money"] = money_section(analysis["load_balancer"], analysis["simulator"], inputs)
    analysis["_provenance"] = {"inputs": sorted(set(_rel(inputs))), "label": UNVALIDATED,
                               "script": "scripts/a2_post_analysis.py"}
    return analysis


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(OUT), help="default: data/a2/post-analysis.json "
                                                    "under the repository root")
    args = ap.parse_args(argv)
    out = Path(args.out)
    text = json.dumps(build(), indent=1, sort_keys=True, allow_nan=False) + "\n"
    out.write_text(text)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
