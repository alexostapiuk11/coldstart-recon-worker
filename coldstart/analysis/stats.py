"""Non-parametric statistics for cold-start measurements.

Every quantity this module reports is a percentile, an ECDF, or a bootstrap
confidence interval on one of those — never a mean or a standard deviation.
Cold-start distributions are right-skewed with a heavy tail (spec 9b); a
mean is pulled by the tail and a standard deviation overstates how tight the
bulk of the distribution is.

Percentile convention: linear interpolation between order statistics —
numpy's ``method="linear"``, which is also numpy's default
(``numpy.percentile``'s ``method``/``interpolation`` argument). This is
deliberately not nearest-rank (``ceil(q * n)``, which selects an existing
observation rather than interpolating between two). The same ``_quantile``
function backs both ``percentiles()`` and the median inside every bootstrap
in this module, so ``percentiles(xs)["p50"]`` and a bootstrap's point
estimate on the same data are the same computation, not two definitions of
"median" that usually happen to agree and occasionally don't.

Confidence interval convention: percentile-method bootstrap intervals — the
alpha/2 and 1-alpha/2 order statistics of the resampled distribution. This
is first-order accurate and known to be biased for skewed statistics (it
does not correct for that skew, the way BCa does); it is used here because
it is simple and well understood, and is defensible as long as it is
stated, which this docstring is doing.

Sample floors: MIN_SAMPLES gates which percentiles ``percentiles()`` is
willing to report — a percentile from too few samples is an observation,
not a measurement (spec 5). MIN_BOOTSTRAP_SAMPLES applies the same
discipline to every bootstrap interval in this module, since every one of
them resamples a median.
"""

import math
import random

# A percentile needs enough samples to be a measurement rather than an
# observation. p99 at n=100 is one or two points — see spec 5. Each entry is
# a pre-registered parameter: changing any one of them changes what this
# module is willing to publish.
MIN_SAMPLES = {"p50": 20, "p90": 50, "p95": 80, "p99": 500}

# Same discipline as MIN_SAMPLES, applied to bootstrap intervals: every
# bootstrap in this module resamples a median, so it inherits p50's floor.
# Without this, bootstrap_median_diff([100.0], [70.0]) would return a
# confident-looking, zero-width "95% CI" built from a single observation —
# the confidence-interval equivalent of reporting p99 from two data points.
MIN_BOOTSTRAP_SAMPLES = MIN_SAMPLES["p50"]


def _validate_samples(values: list[float], name: str) -> list[float]:
    """Fail loudly on the input domains a percentile/bootstrap silently
    mishandles: empty sequences (division by zero, IndexError, or an empty
    `random.randrange` range) and non-finite values (a NaN or inf corrupting
    a sort or a median without raising anywhere)."""
    xs = list(values)
    if not xs:
        raise ValueError(f"{name} must not be empty")
    for v in xs:
        if not math.isfinite(v):
            raise ValueError(f"{name} contains a non-finite value: {v!r}")
    return xs


def _validate_bootstrap_sample(values: list[float], name: str) -> list[float]:
    """`_validate_samples`'s checks, plus MIN_BOOTSTRAP_SAMPLES: a thin
    sample must not be allowed to bootstrap to a confident-looking interval.
    """
    xs = _validate_samples(values, name)
    if len(xs) < MIN_BOOTSTRAP_SAMPLES:
        raise ValueError(
            f"{name} has {len(xs)} samples; a bootstrap interval needs at least "
            f"{MIN_BOOTSTRAP_SAMPLES} (the same floor percentiles' p50 uses), or "
            "it is an artifact of a thin sample, not a measurement"
        )
    return xs


def _quantile(sorted_xs: list[float], q: float) -> float:
    """Linear interpolation between order statistics — numpy's
    ``method="linear"``, also numpy's default. At q=0.5 this is exactly the
    textbook median: the average of the two middle values at even n, the
    single middle value at odd n. Every median-shaped computation in this
    module (percentiles' p50, and every bootstrap's point estimate) goes
    through this one function so the same quantity cannot measure
    differently in two places in the same publication.

    `sorted_xs` must already be sorted; this does not sort, since a
    bootstrap calls it once per resample and paying to re-sort here (on top
    of the sort `_median` already does) would double the cost for nothing.
    """
    n = len(sorted_xs)
    idx = q * (n - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return sorted_xs[lo]
    frac = idx - lo
    return sorted_xs[lo] * (1 - frac) + sorted_xs[hi] * frac


def _median(values) -> float:
    """The one median implementation this module uses — see the module
    docstring and `_quantile`. Equivalent to `statistics.median`, expressed
    via `_quantile` so it is textually the same code path as `percentiles`'s
    p50, not a second implementation that happens to agree most of the
    time."""
    return _quantile(sorted(values), 0.5)


def percentiles(values, want=("p50", "p90", "p95")) -> dict[str, float]:
    """Percentiles of `values` at the names in `want` (e.g. "p50", "p90"),
    refusing any name whose MIN_SAMPLES floor `values` doesn't meet. See the
    module docstring for the interpolation convention."""
    xs = sorted(_validate_samples(values, "values"))
    n = len(xs)
    out = {}
    for name in want:
        if name not in MIN_SAMPLES:
            raise ValueError(f"unknown percentile {name!r}; known: {sorted(MIN_SAMPLES)}")
        need = MIN_SAMPLES[name]
        if n < need:
            raise ValueError(
                f"{name} requires at least {need} samples, got {n}; "
                "reporting it would be an observation, not a measurement"
            )
        q = int(name[1:]) / 100.0
        out[name] = _quantile(xs, q)
    return out


def ecdf(values) -> tuple[list[float], list[float]]:
    """Empty input has no well-defined ECDF (the step size divides by n), so
    it is refused rather than silently returning ([], []).

    Tie behavior: a repeated value gets one (x, y) pair per observation, not
    one pair per distinct x — this is the step-function shape a plotter
    expects (e.g. matplotlib's ``plt.step(..., where="post")``), not a
    deduplicated x -> F(x) lookup table. To read the CDF value AT a
    particular x from these arrays, take the y from the LAST occurrence of
    that x; the y at an earlier tied occurrence understates F(x).
    """
    xs = sorted(_validate_samples(values, "values"))
    n = len(xs)
    return xs, [(i + 1) / n for i in range(n)]


def _check_iterations_and_alpha(iterations: int, alpha: float) -> None:
    if iterations <= 0:
        raise ValueError(f"iterations must be positive, got {iterations}")
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be strictly between 0 and 1, got {alpha}")


def _percentile_interval(draws: list[float], alpha: float) -> tuple[float, float]:
    """The one percentile-method endpoint computation every bootstrap in
    this module uses: the alpha/2 and 1-alpha/2 order statistics of the
    resampled distribution `draws`.

    Also the one place the lo <= hi invariant is enforced. With too few
    draws for how extreme `alpha` is, the naive index arithmetic can put the
    "lo" index above the "hi" index and return a backwards interval instead
    of raising. `lo_idx > hi_idx` alone is sufficient: lo_idx = int((alpha/2)
    * n) is always >= 0, so a negative hi_idx (which would otherwise wrap
    around to the end of the sorted list via Python's negative indexing) is
    already > it, and `alpha < 1` (enforced by every caller) keeps lo_idx
    below n. Checking those cases separately would just be the same
    condition twice — see the M1-class cleanup this module already does.
    """
    xs = sorted(draws)
    n = len(xs)
    lo_idx = int((alpha / 2) * n)
    hi_idx = int((1 - alpha / 2) * n) - 1
    if lo_idx > hi_idx:
        raise ValueError(
            f"iterations={n} is too few for alpha={alpha}: the percentile-method "
            f"endpoints would invert (lo index {lo_idx}, hi index {hi_idx}); "
            "increase iterations"
        )
    return xs[lo_idx], xs[hi_idx]


def bootstrap_median_diff(a, b, iterations=10000, seed=0, alpha=0.05) -> dict:
    """Non-parametric interval on median(a) - median(b). No distributional assumption.

    Do not call this on within_host_triples output: it resamples a and b
    independently, which is correct for the pooled, unpaired analysis but
    silently reintroduces the host confound on paired data. Use
    bootstrap_paired_median_diff for that.
    """
    _check_iterations_and_alpha(iterations, alpha)
    a = _validate_bootstrap_sample(a, "a")
    b = _validate_bootstrap_sample(b, "b")
    rng = random.Random(seed)
    point = _median(a) - _median(b)
    draws = []
    for _ in range(iterations):
        ra = [a[rng.randrange(len(a))] for _ in range(len(a))]
        rb = [b[rng.randrange(len(b))] for _ in range(len(b))]
        draws.append(_median(ra) - _median(rb))
    lo, hi = _percentile_interval(draws, alpha)
    return {"point": point, "lo": lo, "hi": hi}


def bootstrap_contrast_difference(a, b, c, iterations=10000, seed=0, alpha=0.05) -> dict:
    """Interval on (A-B) - (B-C): the ranking claim needs its own interval.

    Do not call this on within_host_triples output: it resamples a, b, and c
    independently, which is correct for the pooled, unpaired analysis but
    silently reintroduces the host confound on paired data. Use
    bootstrap_paired_contrast_difference for that.
    """
    _check_iterations_and_alpha(iterations, alpha)
    a = _validate_bootstrap_sample(a, "a")
    b = _validate_bootstrap_sample(b, "b")
    c = _validate_bootstrap_sample(c, "c")
    rng = random.Random(seed)

    def draw(xs):
        return [xs[rng.randrange(len(xs))] for _ in range(len(xs))]

    point = (_median(a) - _median(b)) - (_median(b) - _median(c))
    vals = []
    for _ in range(iterations):
        ra, rb, rc = draw(a), draw(b), draw(c)
        vals.append((_median(ra) - _median(rb)) - (_median(rb) - _median(rc)))
    lo, hi = _percentile_interval(vals, alpha)
    return {"point": point, "lo": lo, "hi": hi}


def within_host_triples(rows, arms=("A", "B", "C")) -> list[list[dict]]:
    """Triples whose runs all landed on one host — the host confound removed.

    A group survives only if the runs cover exactly the required set of
    arms (no missing arm, no duplicate standing in for a missing one) and
    every run shares one host_id. There is no separate "right number of
    runs" check: `sorted(arm list) == sorted(arms)` can only hold at equal
    length, so a group with the wrong count is already rejected by the arm
    check. `sorted()` on `groups.items()` makes the output order
    deterministic by triple_index, rather than incidental to dict iteration
    order.
    """
    groups: dict[int, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["triple_index"], []).append(r)
    kept = []
    for _, g in sorted(groups.items()):
        if sorted(x["arm"] for x in g) != sorted(arms):
            continue
        if len({x["host_id"] for x in g}) != 1:
            continue
        kept.append(g)
    return kept


def _arm_lookup(triple: list[dict]) -> dict[str, dict]:
    """Map arm -> row for one triple, rejecting a duplicate arm outright —
    a duplicate silently shadowing a missing arm is worse than a KeyError."""
    out: dict[str, dict] = {}
    for row in triple:
        arm = row["arm"]
        if arm in out:
            raise ValueError(f"triple has duplicate arm {arm!r}: {triple}")
        out[arm] = row
    return out


def _row_value(row: dict, value) -> float:
    """`value` is a key name or a callable(row) -> float — both t_total and
    t_weights get this treatment, so it is never hardcoded to one field."""
    v = value(row) if callable(value) else row[value]
    if not math.isfinite(v):
        raise ValueError(f"non-finite value in row {row!r}: {v!r}")
    return v


def _paired_delta(triple: list[dict], arm_a: str, arm_b: str, value) -> float:
    lookup = _arm_lookup(triple)
    for arm in (arm_a, arm_b):
        if arm not in lookup:
            raise ValueError(f"triple is missing arm {arm!r}: has {sorted(lookup)}")
    return _row_value(lookup[arm_a], value) - _row_value(lookup[arm_b], value)


def _paired_contrast_delta(triple: list[dict], arms: tuple[str, str, str], value) -> float:
    lookup = _arm_lookup(triple)
    for arm in arms:
        if arm not in lookup:
            raise ValueError(f"triple is missing arm {arm!r}: has {sorted(lookup)}")
    a_val = _row_value(lookup[arms[0]], value)
    b_val = _row_value(lookup[arms[1]], value)
    c_val = _row_value(lookup[arms[2]], value)
    return (a_val - b_val) - (b_val - c_val)


def _bootstrap_median_of_units(deltas: list[float], iterations: int, seed: int, alpha: float) -> dict:
    """Shared engine for both paired bootstraps: `deltas` already holds one
    scalar per independent unit (one per triple). Resampling this list with
    replacement is what makes the unit of resampling the triple rather than
    the individual arm observation inside it.

    Callers are responsible for the MIN_BOOTSTRAP_SAMPLES floor and the
    iterations/alpha check before calling this — checking those here too
    would be a third copy of a check already made once at the public entry
    point, and would run after the (more expensive) per-triple delta
    computation instead of before it.
    """
    rng = random.Random(seed)
    n = len(deltas)
    point = _median(deltas)
    draws = []
    for _ in range(iterations):
        resample = [deltas[rng.randrange(n)] for _ in range(n)]
        draws.append(_median(resample))
    lo, hi = _percentile_interval(draws, alpha)
    return {"point": point, "lo": lo, "hi": hi}


def bootstrap_paired_median_diff(
    triples: list[list[dict]],
    arm_a: str,
    arm_b: str,
    value="t_total",
    iterations=10000,
    seed=0,
    alpha=0.05,
) -> dict:
    """Paired bootstrap on within_host_triples output: the interval on the
    median of arm_a - arm_b, computed once per triple.

    Resamples whole triples with replacement, not individual arm
    observations — the two runs in a triple are not independent draws, they
    share a host, and treating them as interchangeable with runs from other
    triples would reintroduce the host confound within_host_triples exists
    to remove. See bootstrap_median_diff for the unpaired, pooled version.
    """
    _check_iterations_and_alpha(iterations, alpha)
    if arm_a == arm_b:
        raise ValueError(f"arm_a and arm_b must be distinct, both are {arm_a!r}")
    if len(triples) < MIN_BOOTSTRAP_SAMPLES:
        raise ValueError(
            f"triples has {len(triples)} units; a bootstrap interval needs at least "
            f"{MIN_BOOTSTRAP_SAMPLES} (the same floor percentiles' p50 uses), or "
            "it is an artifact of a thin sample, not a measurement"
        )
    deltas = [_paired_delta(t, arm_a, arm_b, value) for t in triples]
    return _bootstrap_median_of_units(deltas, iterations, seed, alpha)


def bootstrap_paired_contrast_difference(
    triples: list[list[dict]],
    arms: tuple[str, str, str] = ("A", "B", "C"),
    value="t_total",
    iterations=10000,
    seed=0,
    alpha=0.05,
) -> dict:
    """Paired bootstrap on within_host_triples output: the interval on the
    median of (A-B) - (B-C), computed once per triple — the ranking claim on
    the cleanest subset of the dataset.

    Resamples whole triples with replacement, not individual arm
    observations; see bootstrap_paired_median_diff and
    bootstrap_contrast_difference for the reasoning and the unpaired version.
    """
    _check_iterations_and_alpha(iterations, alpha)
    if len(arms) != 3:
        raise ValueError(f"arms must have exactly 3 entries, got {arms!r}")
    if len(set(arms)) != 3:
        raise ValueError(f"arms must be distinct, got {arms!r}")
    if len(triples) < MIN_BOOTSTRAP_SAMPLES:
        raise ValueError(
            f"triples has {len(triples)} units; a bootstrap interval needs at least "
            f"{MIN_BOOTSTRAP_SAMPLES} (the same floor percentiles' p50 uses), or "
            "it is an artifact of a thin sample, not a measurement"
        )
    deltas = [_paired_contrast_delta(t, arms, value) for t in triples]
    return _bootstrap_median_of_units(deltas, iterations, seed, alpha)
