"""Artifact 2's non-parametric statistics.

Same conventions as artifact 1, deliberately: linear-interpolation quantiles
(numpy's `method="linear"`), percentile-method bootstrap intervals, and sample
floors gating what may be reported. Two artifacts in one publication reporting
"the median" two different ways is the kind of discrepancy a reader finds and
an author cannot explain.

WHY THIS IS A SECOND IMPLEMENTATION rather than an import of
`coldstart.analysis.stats`: `tests/test_autoscale_boundary.py` enforces that
exactly one file in `autoscale/` imports artifact 1, and that file is the
lag-ECDF adapter -- artifact 2 depends on artifact 1 for measured DATA, not for
library code, which is what keeps the simulator runnable without artifact 1's
store on disk and keeps the pending harness extraction a one-file change. The
duplication is held honest by
`tests/test_autoscale_stats.py::test_it_agrees_with_artifact_ones_implementation`,
which fails if either copy changes alone. When `harness/` exists, this file
becomes an import and that test becomes redundant.

Percentile convention: linear interpolation between order statistics. Not
nearest-rank -- `sorted[int(q * n)]`, which artifact 2's own `SimResult` used
until this module existed, and which disagrees with artifact 1 by up to a whole
order statistic on the same data.

Confidence interval convention: percentile-method bootstrap -- the alpha/2 and
1-alpha/2 order statistics of the resampled distribution. First-order accurate
and known to be biased for skewed statistics (BCa corrects for that; this does
not). Defensible as long as it is stated, which this is.
"""

import math
import random

__all__ = [
    "MIN_BOOTSTRAP_SAMPLES",
    "MIN_SAMPLES",
    "bootstrap_interval",
    "median",
    "percentiles",
    "quantile",
]

# Copied from artifact 1 and pinned equal to it by the conformance test. A
# percentile needs enough samples to be a measurement rather than an
# observation.
MIN_SAMPLES = {"p50": 20, "p90": 50, "p95": 80, "p99": 500}

# Every bootstrap here resamples a median, so it inherits p50's floor.
MIN_BOOTSTRAP_SAMPLES = MIN_SAMPLES["p50"]


def _validate(values, name: str) -> list[float]:
    """Fail loudly on the inputs a quantile or bootstrap silently mishandles.

    NaN is the dangerous one and it is silent: it compares False against every
    ordering test, so `sorted()` leaves it wherever it happened to sit and the
    interpolation below reads two neighbours that are not the ones the quantile
    names. An infinity sorts legitimately and then poisons the arithmetic.
    """
    xs = list(values)
    if not xs:
        raise ValueError(f"{name} must not be empty; there is no quantile of nothing")
    for i, v in enumerate(xs):
        if v is None or not math.isfinite(v):
            raise ValueError(
                f"{name}[{i}] is {v!r}, which is not finite; a NaN compares "
                "False against every ordering test, so it would not sort to a "
                "predictable position and the interpolation would read the "
                "wrong pair of order statistics instead of raising here"
            )
    return xs


def quantile(sorted_xs: list[float], q: float) -> float:
    """Linear interpolation between order statistics.

    `sorted_xs` must already be sorted; this does not sort, because a bootstrap
    calls it once per resample and re-sorting here would double that cost.
    """
    n = len(sorted_xs)
    if n == 0:
        raise ValueError("cannot take a quantile of an empty sample")
    idx = q * (n - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return sorted_xs[lo]
    frac = idx - lo
    return sorted_xs[lo] * (1 - frac) + sorted_xs[hi] * frac


def median(values) -> float:
    """The one median this package uses. Routes through `quantile` so a chart's
    median and a table's p50 are one computation, not two definitions that
    usually agree."""
    return quantile(sorted(_validate(values, "values")), 0.5)


def percentiles(values, want=("p50", "p90", "p95", "p99")) -> dict[str, float]:
    """The requested percentiles, refusing any whose sample floor is unmet.

    Refusing rather than returning-and-flagging: a number in a dict is a number
    a caller will publish, and "p99 from 30 samples" is indistinguishable in a
    figure from "p99 from 30,000".
    """
    xs = _validate(values, "values")
    ordered = sorted(xs)
    out: dict[str, float] = {}
    for name in want:
        floor = MIN_SAMPLES[name]
        if len(ordered) < floor:
            raise ValueError(
                f"{name} needs at least {floor} samples and got {len(ordered)}; "
                "a percentile from too few samples is an observation, not a "
                "measurement, and once it is in the returned dict nothing "
                "downstream can tell it apart from a well-supported one"
            )
        out[name] = quantile(ordered, float(name[1:]) / 100.0)
    return out


def _percentile_interval(draws: list[float], alpha: float) -> tuple[float, float]:
    """The alpha/2 and 1-alpha/2 order statistics of the resampled distribution.

    Also the one place the lo <= hi invariant is enforced: with too few draws
    for how extreme `alpha` is, the naive index arithmetic puts the lo index
    above the hi index and returns a BACKWARDS interval rather than raising.
    """
    xs = sorted(draws)
    n = len(xs)
    lo_idx = int((alpha / 2) * n)
    hi_idx = int((1 - alpha / 2) * n) - 1
    if lo_idx > hi_idx:
        raise ValueError(
            f"iterations={n} is too few for alpha={alpha}: the percentile-method "
            f"endpoints would invert (lo index {lo_idx}, hi index {hi_idx}) and "
            "return a backwards interval instead of raising; increase iterations"
        )
    return xs[lo_idx], xs[hi_idx]


def bootstrap_interval(values, iterations: int = 10000, seed: int = 0, alpha: float = 0.05) -> dict:
    """A percentile-method interval on the median of `values`.

    Returns `{"point", "lo", "hi"}`. `point` is the median of the observed
    sample, not the mean of the bootstrap draws: the draws estimate the
    sampling distribution's SPREAD, and reporting their centre instead would
    publish a subtly different estimator from the one named.
    """
    if iterations <= 0:
        raise ValueError(f"iterations must be positive, got {iterations}")
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be strictly between 0 and 1, got {alpha}")
    xs = _validate(values, "values")
    if len(xs) < MIN_BOOTSTRAP_SAMPLES:
        raise ValueError(
            f"a bootstrap interval needs at least {MIN_BOOTSTRAP_SAMPLES} "
            f"samples and got {len(xs)}; below that the resampled distribution "
            "is a handful of repeated values and the interval comes out "
            "confident-looking and meaningless"
        )
    rng = random.Random(seed)
    point = quantile(sorted(xs), 0.5)
    n = len(xs)
    draws = [
        quantile(sorted(xs[rng.randrange(n)] for _ in range(n)), 0.5) for _ in range(iterations)
    ]
    lo, hi = _percentile_interval(draws, alpha)
    return {"point": point, "lo": lo, "hi": hi}
