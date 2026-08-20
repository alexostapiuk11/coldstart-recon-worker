import math
import random
import statistics

# A percentile needs enough samples to be a measurement rather than an
# observation. p99 at n=100 is one or two points — see spec 5. Each entry is
# a pre-registered parameter: changing any one of them changes what this
# module is willing to publish.
MIN_SAMPLES = {"p50": 20, "p90": 50, "p95": 80, "p99": 500}


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


def percentiles(values, want=("p50", "p90", "p95")) -> dict[str, float]:
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
        idx = min(n - 1, max(0, round(q * (n - 1))))
        out[name] = xs[idx]
    return out


def ecdf(values) -> tuple[list[float], list[float]]:
    """Empty input has no well-defined ECDF (the step size divides by n), so
    it is refused rather than silently returning ([], [])."""
    xs = sorted(_validate_samples(values, "values"))
    n = len(xs)
    return xs, [(i + 1) / n for i in range(n)]


def _check_iterations_and_alpha(iterations: int, alpha: float) -> None:
    if iterations <= 0:
        raise ValueError(f"iterations must be positive, got {iterations}")
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be strictly between 0 and 1, got {alpha}")


def bootstrap_median_diff(a, b, iterations=10000, seed=0, alpha=0.05) -> dict:
    """Non-parametric interval on median(a) - median(b). No distributional assumption.

    Do not call this on within_host_triples output: it resamples a and b
    independently, which is correct for the pooled, unpaired analysis but
    silently reintroduces the host confound on paired data. Use
    bootstrap_paired_median_diff for that.
    """
    _check_iterations_and_alpha(iterations, alpha)
    a = _validate_samples(a, "a")
    b = _validate_samples(b, "b")
    rng = random.Random(seed)
    point = statistics.median(a) - statistics.median(b)
    draws = []
    for _ in range(iterations):
        ra = [a[rng.randrange(len(a))] for _ in range(len(a))]
        rb = [b[rng.randrange(len(b))] for _ in range(len(b))]
        draws.append(statistics.median(ra) - statistics.median(rb))
    draws.sort()
    lo = draws[int((alpha / 2) * iterations)]
    hi = draws[int((1 - alpha / 2) * iterations) - 1]
    return {"point": point, "lo": lo, "hi": hi}


def bootstrap_contrast_difference(a, b, c, iterations=10000, seed=0, alpha=0.05) -> dict:
    """Interval on (A-B) - (B-C): the ranking claim needs its own interval.

    Do not call this on within_host_triples output: it resamples a, b, and c
    independently, which is correct for the pooled, unpaired analysis but
    silently reintroduces the host confound on paired data. Use
    bootstrap_paired_contrast_difference for that.
    """
    _check_iterations_and_alpha(iterations, alpha)
    a = _validate_samples(a, "a")
    b = _validate_samples(b, "b")
    c = _validate_samples(c, "c")
    rng = random.Random(seed)
    med = statistics.median

    def draw(xs):
        return [xs[rng.randrange(len(xs))] for _ in range(len(xs))]

    point = (med(a) - med(b)) - (med(b) - med(c))
    vals = []
    for _ in range(iterations):
        ra, rb, rc = draw(a), draw(b), draw(c)
        vals.append((med(ra) - med(rb)) - (med(rb) - med(rc)))
    vals.sort()
    return {
        "point": point,
        "lo": vals[int((alpha / 2) * iterations)],
        "hi": vals[int((1 - alpha / 2) * iterations) - 1],
    }


def within_host_triples(rows, arms=("A", "B", "C")) -> list[list[dict]]:
    """Triples whose runs all landed on one host — the host confound removed.

    A group survives only if it has exactly the right number of runs, the
    runs cover exactly the required set of arms (no missing arm, no
    duplicate standing in for a missing one), and every run shares one
    host_id.
    """
    groups: dict[int, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["triple_index"], []).append(r)
    kept = []
    for _, g in sorted(groups.items()):
        if len(g) != len(arms):
            continue
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
    the individual arm observation inside it."""
    _check_iterations_and_alpha(iterations, alpha)
    if not deltas:
        raise ValueError("deltas must not be empty")
    rng = random.Random(seed)
    n = len(deltas)
    point = statistics.median(deltas)
    draws = []
    for _ in range(iterations):
        resample = [deltas[rng.randrange(n)] for _ in range(n)]
        draws.append(statistics.median(resample))
    draws.sort()
    lo = draws[int((alpha / 2) * iterations)]
    hi = draws[int((1 - alpha / 2) * iterations) - 1]
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
    if not triples:
        raise ValueError("triples must not be empty")
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
    if len(arms) != 3:
        raise ValueError(f"arms must have exactly 3 entries, got {arms!r}")
    if not triples:
        raise ValueError("triples must not be empty")
    deltas = [_paired_contrast_delta(t, arms, value) for t in triples]
    return _bootstrap_median_of_units(deltas, iterations, seed, alpha)
