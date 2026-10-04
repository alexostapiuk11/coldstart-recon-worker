"""Artifact 1's measured cold-start distributions, as a resampling source.

The ONLY module in this package that imports `coldstart`. Everything else takes
plain numbers, which keeps the simulator testable without artifact 1's data on
disk and confines the pending harness extraction to one file.

Resampling, not fitting. Artifact 1 measured p95/p50 of about 1.2 on both arms;
fitting a parametric tail to that would invent structure the data does not show,
and the tail is exactly where an autoscaling simulation is most sensitive.

Two defects whose root cause lives in `coldstart/` are worked around here rather
than there, because artifact 1 is published and is being corrected separately:
the `run_index` merge in `load_measured_lags` (see its comment) and the sample
validation in `LagDistribution.__post_init__`. Both are defensive local fixes.
If artifact 1's versions are repaired, these stay -- they are cheap, and this
module is the boundary where a bad number stops being artifact 1's problem and
starts being a wrong simulation result.
"""

import math
import random
from dataclasses import dataclass
from pathlib import Path

from coldstart.analysis.metrics import derive
from coldstart.analysis.pipeline import (
    REQUIRED_FOR_T_TOTAL,
    annotate_first_touch,
    partition,
)
from coldstart.store import JsonlStore
from harness.stats import median as _stats_median

__all__ = ["LagDistribution", "load_measured_lags"]

DEFAULT_EXPECTED_ARMS: tuple[str, ...] = ("A", "B", "C")


@dataclass
class LagDistribution:
    """An empirical distribution of scale-up lag, in seconds.

    `samples` is the measured population itself, not summary statistics: a draw
    returns a value the campaign actually observed or it returns nothing.
    """

    samples: list[float]

    def __post_init__(self) -> None:
        if not self.samples:
            raise ValueError(
                "a lag distribution needs at least one sample; an empty one "
                "would make every scale-up instantaneous and silently turn the "
                "simulation into a no-cold-start baseline"
            )
        for i, v in enumerate(self.samples):
            # `None` and non-finite are rejected for the same reason
            # `harness.stats._validate_samples` rejects them, checked
            # here as well because a distribution is built once and then drawn
            # from thousands of times: the stats call that would have caught a
            # NaN might not run until after a whole sweep has been simulated on
            # it. A NaN lag makes every `<`/`>` against a queue deadline
            # silently False and medians to NaN; a negative one has no physical
            # reading at all -- a replica cannot be ready before it was asked
            # for -- and would credit the scheduler with time it never had.
            if v is None:
                raise ValueError(
                    f"lag sample [{i}] is None; a None lag propagates as a "
                    "TypeError from somewhere deep in the queue arithmetic, or "
                    "worse, medians to None and is reported as a result"
                )
            if not isinstance(v, (int, float)):
                # ValueError, not TypeError (noqa: TRY004): every sibling check
                # in this validator -- None, non-finite, negative -- raises
                # ValueError naming the index and value, and a caller iterating
                # bad samples should be able to catch one exception type for
                # all of them.
                raise ValueError(  # noqa: TRY004
                    f"lag sample [{i}] is not a number ({v!r}); "
                    "math.isfinite raises a bare TypeError on anything that "
                    "isn't, with no index or value attached to say which "
                    "sample was bad"
                )
            if not math.isfinite(v):
                raise ValueError(
                    f"lag sample [{i}] is non-finite ({v!r}); it would make "
                    "every queue-time comparison against it silently False and "
                    "every percentile of this arm NaN"
                )
            if v < 0:
                raise ValueError(
                    f"lag sample [{i}] is negative ({v!r}); a negative scale-up "
                    "lag means a replica became ready before it was requested, "
                    "and would let the simulation serve requests early"
                )

    def sample(self, rng: random.Random) -> float:
        """One draw. `rng` is supplied by the caller so a whole simulation run
        is reproducible from a single seed."""
        return rng.choice(self.samples)

    def median(self) -> float:
        """Delegates to `harness.stats.median` deliberately.

        That function's own docstring exists to stop a second definition of
        "median" being written -- "they are one computation, not two
        definitions of 'median' that usually happen to match". A local
        implementation here would agree with it on essentially every input,
        which is precisely why a divergence (percentile convention, even-length
        handling, validation) would never be caught by a test. Delegating means
        artifact 2's medians cannot silently disagree with artifact 1's
        published medians on the same data. This module is already the one file
        allowed to import `coldstart`, so nothing architectural is spent on it.
        """
        return _stats_median(self.samples)


def load_measured_lags(
    store_path: str | Path,
    expected_arms: tuple[str, ...] = DEFAULT_EXPECTED_ARMS,
) -> dict[str, LagDistribution]:
    """Artifact 1's per-arm lag distributions, keyed by arm.

    Repeat-host runs only. Artifact 1's one first-touch run took 2266.6 s
    against a 39-96 s norm because the host had never pulled the image; it is
    a platform event, not a cold start, and artifact 1 excluded it from its own
    ECDF on a mechanical first-on-its-host rule applied to every run. The same
    rule applies here. Host novelty is carried as a named risk and recorded per
    replica during validation instead.

    Raises rather than returning a partial dict on every input that cannot
    produce a trustworthy distribution: a missing store, a store with no
    publishable rows, a store with no repeat-host rows, and a store missing any
    arm in `expected_arms`. Each of those used to return `{}` or a short dict,
    and a short dict is the dangerous one -- a sweep over a silently absent arm
    reports no cold-start cost for it rather than failing.

    `expected_arms` must be passed explicitly for any campaign whose arms are
    not artifact 1's A/B/C -- the default is that specific tuple, not a
    wildcard, so a differently-armed campaign left on the default would be
    read as missing every arm it actually has.
    """
    path = Path(store_path)
    # Checked before JsonlStore is constructed: its __init__ mkdirs the parent,
    # so constructing it on a typo'd path both creates directories on disk and
    # then reads back an empty campaign.
    if not path.exists():
        raise FileNotFoundError(
            f"no run store at {path}; without it there is no measured lag "
            "distribution, and a simulation built on an empty one would report "
            "an autoscaler that never pays a cold start"
        )

    records = JsonlStore(path).read_all()

    # The `run_index` merge is load-bearing, not tidiness. `annotate_first_touch`
    # documents its ordering as "deterministic and independent of read order"
    # because it sorts by `run_index` -- but `metrics.derive()` does not emit a
    # `run_index` key, so `r.get("run_index", 0)` returns 0 for every row, the
    # sort is stable, and it degrades to whatever order the file happened to be
    # in. Reversing this store moves the excluded run from arm A (the 2266.6 s
    # first-touch one) to an unrelated 70.5 s arm-B run: the pool sizes still
    # sum to 299 and the medians still land where they should, so the module's
    # entire stated purpose stops happening without anything failing. The raw
    # `RunRecord` still carries `run_index`, so it is carried across the
    # `derive()` boundary by hand. The root defect is in `coldstart/` (either
    # `derive()` should emit the key or `annotate_first_touch` should refuse a
    # row without it); this is the defensive local fix.
    rows = annotate_first_touch([{**derive(r), "run_index": r.run_index} for r in records])
    publishable = partition(rows, required=REQUIRED_FOR_T_TOTAL).publishable

    if not publishable:
        raise ValueError(
            f"{path} yielded no publishable rows; there is nothing to resample "
            "from, and every arm would draw a lag of zero"
        )

    by_arm: dict[str, list[float]] = {}
    for row in publishable:
        # `is not False`, not `not row.get("first_touch")`: a row whose
        # `first_touch` is None has no `host_id` at all, so whether it was first
        # on its host is unknown, and unknown is excluded here rather than
        # optimistically read as "repeat".
        if row.get("first_touch") is not False:
            continue
        by_arm.setdefault(row["arm"], []).append(row["t_total"])

    # Both sides of this guard are computed over `rows` -- the full population
    # `annotate_first_touch` actually annotated -- not over `publishable`. A
    # host whose first-on-its-host run failed or was discarded still appears
    # as a host in `publishable` (via its other, repeat-host rows) while its
    # own `first_touch=True` row does not (it landed in `failed` or
    # `discarded` instead), which used to undercount "seen" against
    # "expected" on an entirely ordinary campaign. Failed and discarded runs
    # are normal -- `partition()` has buckets for exactly this, and artifact 1
    # publishes their rates -- so the guard must not treat one as evidence of
    # its own malfunction.
    #
    # What this assertion actually checks: that `annotate_first_touch` marked
    # exactly one first-touch run per distinct host, i.e. its own documented
    # invariant held. It does NOT detect an ordering or key regression in that
    # function -- an ordering bug still marks exactly one row per host, just
    # the wrong one, so `seen == expected` here regardless. Protection against
    # that class of defect comes from
    # `test_the_same_run_is_excluded_when_the_store_is_read_backwards` in
    # tests/test_coldstart_ecdf.py, not from this guard; do not read this
    # guard's presence as covering that case and remove that test.
    expected_first_touch = len({r["host_id"] for r in rows if r.get("host_id")})
    seen_first_touch = sum(1 for r in rows if r.get("first_touch") is True)
    if seen_first_touch != expected_first_touch:
        raise ValueError(
            f"{path}: found {seen_first_touch} first-touch run(s) across "
            f"{expected_first_touch} distinct host(s), expected one per host; "
            "the first-on-its-host exclusion did not run as intended, so a "
            "platform image-pull may be pooled into the cold-start ECDF"
        )

    if not by_arm:
        raise ValueError(
            f"{path} contains publishable rows but no repeat-host ones -- every "
            "run was first on its host. That is a readable campaign, not an "
            "unreadable store, but it measures image distribution rather than "
            "cold start, so there is no lag distribution to build from it"
        )

    missing = [arm for arm in expected_arms if arm not in by_arm]
    if missing:
        raise ValueError(
            f"{path} produced no repeat-host runs for arm(s) {', '.join(missing)} "
            f"(got {', '.join(sorted(by_arm))}); a sweep over a silently absent "
            "arm would report it as costing no cold-start time at all rather "
            "than failing"
        )

    return {arm: LagDistribution(samples=vals) for arm, vals in by_arm.items()}
