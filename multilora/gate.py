"""The equivalence gate (amendment §4).

Statistic, per instance: (synthetic - real) / real, each side aggregated over
its two phases, for TTFT p50 and throughput. Margin delta = tau / 2.

- pass: the 90% bootstrap interval of the median statistic lies inside
  +/- delta for both metrics -- two one-sided tests at the 5% level.
- inconclusive: the same statistic for the first real phase against the
  second does not fit inside +/- delta. The gate then cannot resolve delta,
  and "no difference found" would mean nothing. Single phases are noisier than
  the gate's two-phase aggregates, so this check is conservative.
- fail: otherwise.
"""

from harness.stats import bootstrap_median_ci
from multilora.conditions import REAL, SYNTHETIC

GATE_METRICS = ("ttft_p50", "throughput_tps")
ALPHA = 0.10


def _inside(ci: dict, delta: float) -> bool:
    return -delta < ci["lo"] and ci["hi"] < delta


def verdict(rows: list[dict], delta: float, iterations=10000, seed=0) -> dict:
    metrics = {}
    for m in GATE_METRICS:
        rel = [(r[SYNTHETIC][m] - r[REAL][m]) / r[REAL][m] for r in rows]
        resolution = [
            (r["real_phases"][1][m] - r["real_phases"][0][m]) / r["real_phases"][0][m]
            for r in rows
        ]
        ci = bootstrap_median_ci(rel, iterations=iterations, seed=seed, alpha=ALPHA)
        res_ci = bootstrap_median_ci(resolution, iterations=iterations, seed=seed, alpha=ALPHA)
        metrics[m] = {
            "statistic": ci,
            "per_instance": rel,
            "resolution": res_ci,
            "inside": _inside(ci, delta),
            "resolved": _inside(res_ci, delta),
        }
    if not all(v["resolved"] for v in metrics.values()):
        outcome = "inconclusive"
    elif all(v["inside"] for v in metrics.values()):
        outcome = "pass"
    else:
        outcome = "fail"
    return {"delta": delta, "alpha": ALPHA, "n": len(rows), "metrics": metrics, "verdict": outcome}
