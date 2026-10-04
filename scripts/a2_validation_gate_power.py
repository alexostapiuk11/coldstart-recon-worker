"""How often the validation gate fails a perfect model, and how often it catches
a biased one, when neighbouring bins are NOT independent.

docs/experiment-a2.md ("Validation gate — pass rule") justifies its miss-rate
rule with binomial arithmetic: three repeats bracket a perfect model's bin with
probability 3/4, so the miss count over k judged bins is Binomial(k, 1/4). That
assumes the bins are independent, and a real open-loop run's bins are not: a
queue that builds in one bin is still there in the next, and a slow host slows
every bin of its run. The binomial figures alone would therefore overstate how
well the gate behaves, in the flattering direction. This Monte Carlo puts
numbers on the correlated cases instead, so the pre-registration can quote
them. It runs the repository's own `band()` and `compare()` at artifact 2's
repeat count, bin width, minimum judged bins and miss fraction, not a
re-implementation that could drift from the gate it describes.

One constant is deliberately not the gate's: the band-edge tolerance is 0, not
`BAND_EDGE_TOLERANCE_SECONDS` (1 ms). The scenarios' latency scale is an
arbitrary choice, and 1 ms is a different fraction of each bin's spread under
each choice. Under the independent scenario's spread (about 27 ms per bin p50)
it lowered the perfect model's failure rate at 10 bins from 2.0% to 1.3% in a
4000-trial run -- an effect of the units picked, not of the rule. At 0 the
independent scenario reproduces the binomial arithmetic, which is the check
that the harness is right. The real tolerance only widens the band, so it
makes BOTH models pass more often, by an amount set by how wide real bins are.

Three scenarios, each with its own fixed seed so any one reproduces alone:

- independent: each bin's latencies are lognormal draws, no shared state. The
  control: its failure rates should match the binomial arithmetic.
- queue: one FIFO server at utilisation 0.92 (Poisson schedule at 10 rps,
  exponential service with mean 0.092 s), Lindley recursion. ONE arrival
  schedule is drawn per bin count and shared by every run, as the gate
  requires; runs differ only in their service draws. Neighbouring bins share
  queue state.
- queue + host speed: the same, with every service time of a run scaled by one
  lognormal factor of 5% standard deviation -- host-to-host variation that
  moves every bin of a repeat together.

The "perfect" model predicts each bin's true median p50 (from REFERENCE_RUNS
runs). The "biased" model predicts the quantile q with q^3 + (1-q)^3 = 3/4: a
model three repeats would leave outside in three bins of four if bins were
independent -- "biased beyond the system's own spread", in the
pre-registration's words. Each trial draws REPEATS fresh runs as the band.

Result, 2026-10-03, TRIALS = 10000 per cell (perfect and biased), seeds below:

    scenario                 k  perfect fails  biased fails  lag-1 bin corr
    independent             10          2.0%         92.2%           +0.00
    independent             12          1.5%         94.6%           +0.00
    independent             30          0.1%         99.7%           +0.00
    queue rho=0.92          10          2.5%         85.0%           +0.47
    queue rho=0.92          12          2.4%         86.6%           +0.50
    queue rho=0.92          30          0.4%         92.8%           +0.62
    queue + host speed 5%   10          5.7%         78.8%           +0.70
    queue + host speed 5%   12          4.9%         80.6%           +0.74
    queue + host speed 5%   30          3.9%         80.3%           +0.91

The independent rows match the binomial (2.0%, 1.4%, 0.08%; 92.2%, 94.6%,
99.7%). Queue correlation raises the perfect-model failure rate to about 2.5%
at 10-12 judged bins; a per-run speed effect holds it near 5% (4-6%) however
many bins are judged, and the gate's power against the biased model falls to
near 80%. 10000 trials put a binomial standard error of about 0.16 points on a
2.5% rate, 0.22 on 5% and 0.40 on 80%, enough for the rounded figures the
pre-registration quotes. A 4000-trial run (about 20 s) agreed to within
half a point on every perfect-model rate and a point on every biased one.
The whole run takes about 40 s.

numpy is not a declared dependency; it arrives with matplotlib, which is.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from autoscale.validation import (
    BIN_SECONDS,
    MAX_MISS_FRACTION,
    MIN_COMPARED_BINS,
    REPEATS,
)
from autoscale.validation_band import Bin, band, compare

TRIALS = 10000
REFERENCE_RUNS = 20000
BIN_COUNTS = (10, 12, 30)
# Fixed and distinct, so each scenario reproduces on its own.
SEEDS = {"independent": 7, "queue rho=0.92": 11, "queue + host speed 5%": 13}
RATE_PER_SECOND = 10.0
MEAN_SERVICE_SECONDS = 0.092  # utilisation 0.92 at 10 rps
HOST_SPEED_SD = 0.05
REQUESTS_PER_INDEPENDENT_BIN = 200
# Zero, not the gate's 1 ms (`BAND_EDGE_TOLERANCE_SECONDS`): see the docstring.
EDGE_TOLERANCE_SECONDS = 0.0


def _biased_quantile() -> float:
    """q in (1/2, 1) with q^R + (1-q)^R = 3/4, by bisection: a prediction at
    this quantile falls outside R independent repeats with probability 3/4."""
    lo, hi = 0.5, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if mid**REPEATS + (1 - mid) ** REPEATS < 0.75:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _independent(rng, runs: int, bins: int) -> np.ndarray:
    lat = rng.lognormal(0.0, 0.3, size=(runs, bins, REQUESTS_PER_INDEPENDENT_BIN))
    return np.median(lat, axis=2)


def _queue(rng, runs: int, bins: int, schedule: np.ndarray, speed_sd: float) -> np.ndarray:
    """Per-run, per-bin p50 of one FIFO server's sojourn times on `schedule`."""
    n = len(schedule)
    factor = np.exp(rng.normal(0.0, speed_sd, runs)) if speed_sd else np.ones(runs)
    service = rng.exponential(MEAN_SERVICE_SECONDS, size=(runs, n)) * factor[:, None]
    latency = np.empty((runs, n))
    free = np.zeros(runs)
    for i in range(n):
        free = np.maximum(free, schedule[i]) + service[:, i]
        latency[:, i] = free - schedule[i]
    which = np.minimum((schedule // BIN_SECONDS).astype(int), bins - 1)
    return np.stack([np.median(latency[:, which == j], axis=1) for j in range(bins)], axis=1)


def _generator(name: str, rng, bins: int):
    """A function runs -> (runs, bins) array of p50s for one scenario. The
    queue scenarios draw their ONE schedule here, shared by every run."""
    if name == "independent":
        return lambda runs: _independent(rng, runs, bins)
    count = int(RATE_PER_SECOND * BIN_SECONDS * bins)
    schedule = np.sort(rng.uniform(0.0, BIN_SECONDS * bins, count))
    speed_sd = HOST_SPEED_SD if "host speed" in name else 0.0
    return lambda runs: _queue(rng, runs, bins, schedule, speed_sd)


def _bins(p50s) -> list[Bin]:
    return [Bin(j * BIN_SECONDS, (j + 1) * BIN_SECONDS, 20, 20, 0, float(v), "ok")
            for j, v in enumerate(p50s)]


def _fails(prediction, repeats) -> bool:
    tolerance = band([_bins(r) for r in repeats], min_repeats=REPEATS)
    v = compare(_bins(prediction), tolerance, min_compared_bins=MIN_COMPARED_BINS,
                max_miss_fraction=MAX_MISS_FRACTION,
                edge_tolerance_seconds=EDGE_TOLERANCE_SECONDS)
    if v.outcome == "not_evaluable":
        raise RuntimeError(
            f"{v.compared} judged bins; every bin here is 'ok', so a not-evaluable "
            "verdict means the scenario was built wrong and its rates would be "
            "counted as passes"
        )
    return v.outcome == "failed"


def run(name: str, bins: int, trials: int, quantile: float) -> dict:
    rng = np.random.default_rng([SEEDS[name], bins])
    draw = _generator(name, rng, bins)
    reference = draw(REFERENCE_RUNS)
    perfect = np.median(reference, axis=0)
    biased = np.quantile(reference, quantile, axis=0)
    sims = draw(REPEATS * trials).reshape(trials, REPEATS, bins)
    corr = np.mean([np.corrcoef(reference[:, j], reference[:, j + 1])[0, 1]
                    for j in range(bins - 1)])
    return {
        "scenario": name,
        "bins": bins,
        "perfect_fails": float(np.mean([_fails(perfect, s) for s in sims])),
        "biased_fails": float(np.mean([_fails(biased, s) for s in sims])),
        "lag1_corr": float(corr),
    }


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=TRIALS)
    args = ap.parse_args()
    quantile = _biased_quantile()
    print(f"biased model at quantile {quantile:.4f}; {args.trials} trials per cell")
    print(f"{'scenario':22s} {'k':>3s}  {'perfect fails':>13s}  {'biased fails':>12s}  "
          f"{'lag-1 bin corr':>14s}")
    for name in SEEDS:
        for bins in BIN_COUNTS:
            r = run(name, bins, args.trials, quantile)
            print(f"{name:22s} {bins:3d}  {r['perfect_fails']:12.1%}  "
                  f"{r['biased_fails']:12.1%}  {r['lag1_corr']:+14.2f}")


if __name__ == "__main__":
    main()
