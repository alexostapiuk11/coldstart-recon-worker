"""Pareto frontiers, the iso-cost slice, and H3's verdict.

Frontiers rather than points, because every policy has thresholds and whichever
set you publish decides the winner. Comparing frontiers is what makes the
comparison fair and robust to the objection that the loser was mistuned.
"""

import math
import random
from collections.abc import Iterable
from dataclasses import dataclass

from autoscale import stats
from autoscale.signals import SIGNALS

__all__ = [
    "COMPARED_SIGNALS",
    "H3Verdict",
    "PolicyPoint",
    "gap_at_iso_cost",
    "gap_interval",
    "h3_verdict",
    "iso_cost_budget",
    "pareto_frontier",
]

# The signal set every published gap is a spread ACROSS. Taken from the signal
# registry rather than written out, so it is the same three the sweep runs and
# the same three `figures` refuses to draw without -- a fourth signal added to
# the registry is then compared, not silently left out of the headline.
COMPARED_SIGNALS = frozenset(SIGNALS)


@dataclass(frozen=True)
class PolicyPoint:
    """One policy's outcome, carrying the repetitions it was estimated from.

    It used to carry two scalars -- the MEAN cost and MEAN p99 across
    repetitions -- and nothing else. A 30-repetition estimate and a
    1-repetition estimate were then indistinguishable to every consumer, so no
    figure could show an interval and the published H3 gap had no uncertainty
    attached to it at all. The samples are kept instead, and the scalars are
    derived: 55 policies x 30 repetitions x 2 floats is nothing to hold, and it
    is what lets `gap_interval` resample repetitions and rebuild the frontier
    inside each draw, propagating uncertainty THROUGH the frontier selection
    rather than around it.

    The point estimate is the MEDIAN, not the mean it used to be. Artifact 1's
    standing rule -- never a mean or a standard deviation for right-skewed data
    -- applies to per-run p99s as much as to raw latencies: a single
    catastrophic repetition moves a 30-run mean by a thirtieth of its own
    excess, and under a heavy-tailed workload that repetition is the normal
    case, not an outlier. The estimand is unchanged and still per-run -- the p99
    a TYPICAL run of this policy delivers -- and "typical" is what a median
    reports. The pre-registration fixes the repetition count but not the
    aggregator, so this is a documented change of estimator, disclosed in
    docs/experiment-a2.md rather than made silently.
    """

    cost_samples: tuple[float, ...]  # replica-seconds, one per kept repetition
    p99_samples: tuple[float, ...]  # seconds of request latency, the same runs
    signal: str
    scale_up_at: float
    scale_down_at: float
    # WHICH repetitions these samples came from, not merely how many. The
    # pre-registered exclusion rules discard runs, and they discard different
    # runs for different policies -- a real sweep comes back with 26, 29 and 30
    # surviving repetitions on three policies of the same arm. Positions in
    # `p99_samples` are then NOT comparable across policies: index 3 might be
    # repetition 3 for one policy and repetition 4 for another that lost an
    # earlier run. Since the whole point of the shared seed is that repetition
    # r is the same arrival trace for every policy, `gap_interval` has to pair
    # on the repetition's identity rather than on its position.
    #
    # Defaults to `range(len(samples))`, which is right for a point built by
    # hand and for any sweep that discarded nothing.
    rep_indices: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "cost_samples", tuple(self.cost_samples))
        object.__setattr__(self, "p99_samples", tuple(self.p99_samples))
        if self.rep_indices is None:
            object.__setattr__(self, "rep_indices", tuple(range(len(self.p99_samples))))
        else:
            object.__setattr__(self, "rep_indices", tuple(self.rep_indices))

        if not self.cost_samples or not self.p99_samples:
            raise ValueError(
                "a policy point with no repetitions is a configuration that "
                "produced nothing, not a policy that scored zero; `run_sweep` "
                "skips those rather than emitting a point, so reaching here "
                "means a caller built one by hand"
            )
        if len(self.cost_samples) != len(self.p99_samples):
            raise ValueError(
                f"cost has {len(self.cost_samples)} samples and p99 has "
                f"{len(self.p99_samples)}; both axes of a point come from the "
                "SAME runs, and `gap_interval` resamples one index list for "
                "both -- unequal lengths mean the two axes were computed over "
                "different repetition sets, and pairing them is meaningless"
            )
        if len(self.rep_indices) != len(self.p99_samples):
            raise ValueError(
                f"rep_indices has {len(self.rep_indices)} entries and there are "
                f"{len(self.p99_samples)} samples; the indices say WHICH "
                "repetition each sample came from, so one per sample or the "
                "pairing `gap_interval` depends on is built on a mislabelled "
                "correspondence"
            )
        if len(set(self.rep_indices)) != len(self.rep_indices):
            raise ValueError(
                f"rep_indices {self.rep_indices} contains duplicates; two "
                "samples cannot both be repetition r, and a duplicate would let "
                "one run be drawn twice per bootstrap resample while another is "
                "never drawn at all"
            )

        # The same guards this class has always had, applied to the samples the
        # scalars are now computed from. A NaN is the dangerous case and it is
        # silent in both directions: a NaN p99 fails `point.p99 < best_p99`, so
        # the point is DROPPED from its own frontier -- an arm whose runs
        # produced garbage would publish a frontier that simply omits them,
        # looking sparser rather than broken. A NaN cost fails `p.cost <= cost`
        # in `_p99_at_cost`, so the point is invisible at every iso-cost slice.
        # An infinite cost passes every comparison as an ordinary extreme value
        # and would sit on the frontier as affordable-at-infinity.
        for field_name, samples in (("cost", self.cost_samples), ("p99", self.p99_samples)):
            for i, value in enumerate(samples):
                if not math.isfinite(value):
                    raise ValueError(
                        f"{field_name}_samples[{i}] is {value!r}, which is not "
                        "finite; a NaN compares False against every ordering "
                        "test in pareto_frontier and _p99_at_cost, so the point "
                        "would be silently dropped from its own frontier "
                        "instead of raising here, and an infinity would sit on "
                        "the frontier as an ordinary extreme value"
                    )
                # Both axes are physical readings with a floor: replica-seconds
                # is an integral of a non-negative replica count, latency is a
                # duration. Lower is better on both, so a negative value does
                # not read as a small one but as a WINNING one, dominating
                # every honest point on the frontier.
                if value < 0:
                    raise ValueError(
                        f"{field_name}_samples[{i}] is {value!r}, which is "
                        "negative; lower is better on both frontier axes, so a "
                        "negative value does not read as a small one but as a "
                        "point that dominates every honest policy in the sweep"
                    )
        for field_name, value in (
            ("scale_up_at", self.scale_up_at),
            ("scale_down_at", self.scale_down_at),
        ):
            if not math.isfinite(value):
                raise ValueError(
                    f"{field_name} is {value!r}, which is not finite; a policy "
                    "threshold is a number the controller compares against, and "
                    "a NaN one never fires while an infinite one never stops"
                )

    @property
    def n(self) -> int:
        """Repetitions kept. NOT the pre-registered 30 -- the exclusion rules
        discard runs, and a point built from 4 surviving repetitions has to be
        distinguishable from one built from 30."""
        return len(self.p99_samples)

    @property
    def cost(self) -> float:
        return stats.median(self.cost_samples)

    @property
    def p99(self) -> float:
        return stats.median(self.p99_samples)

    def p99_interval(self, iterations: int = 10000, seed: int = 0) -> tuple[float, float]:
        """A 95% percentile-bootstrap interval on this policy's p99."""
        got = stats.bootstrap_interval(self.p99_samples, iterations=iterations, seed=seed)
        return got["lo"], got["hi"]

    def cost_interval(self, iterations: int = 10000, seed: int = 0) -> tuple[float, float]:
        got = stats.bootstrap_interval(self.cost_samples, iterations=iterations, seed=seed)
        return got["lo"], got["hi"]


@dataclass(frozen=True)
class H3Verdict:
    holds: bool
    partial: bool
    detail: str
    # A third state, distinct from `holds=False`. "The gap at least halved" has
    # no truth value when there was no gap under arm A to halve: the halving is
    # vacuous, not observed. Reporting that as `holds=True` would confirm the
    # artifact's headline from two identical zeros, and reporting it as
    # `holds=False` would publish a refutation the data does not support
    # either. Defaults to True so an ordinary verdict constructs unchanged.
    evaluable: bool = True


# Two costs closer than this, relatively, are the SAME operating point.
#
# `replica_seconds` is an integral accumulated by float addition over the
# event loop, so two policies that hold an identical fleet for an identical
# time come back differing in the last few bits: 669.9999999999985 against
# 670.000000000001, about 4e-15 relative. Anything a physical difference could
# produce is enormously larger -- one replica-second on a 670 s integral is
# 1.5e-3 -- so 1e-9 sits six orders of magnitude above the noise and six below
# the smallest real step, and nothing in the sweep lands in between.
COST_TIE_RELATIVE_TOLERANCE = 1e-9


def pareto_frontier(points: list[PolicyPoint]) -> list[PolicyPoint]:
    """Non-dominated points, ascending by cost. Lower cost and lower p99 are
    both better, so a point is dominated when another is at least as good on
    both axes.

    Costs within `COST_TIE_RELATIVE_TOLERANCE` count as EQUAL, and only the
    best-p99 point of a tied group survives. Comparing them exactly was a real
    defect, not a theoretical one: on the arm-A sweep all 19 queue_depth
    policies cost the same 670 replica-seconds, but float dust in the 13th
    significant digit made three of them a strictly-improving staircase, and
    `pareto_frontier` published that as a Pareto frontier. Which three survived
    was decided by rounding error.

    It did two kinds of damage. `figures.frontiers` drew the signal as a
    vertical smear of dots with no interval band -- `fill_between` over a
    zero-width x-range draws nothing -- on the series carrying this artifact's
    headline finding, that queue depth is the WORST signal and no hypothesis
    named it. And `gap_at_iso_cost` takes `min(p99)` over affordable points, so
    an iso-cost budget landing between two dust values would have moved the
    published gap. Measured on the committed sweep, it does not today: the
    budget sits well above the tied cluster and the gap is identical to four
    decimals either way. A silent dependency on the 13th digit that happens not
    to fire is still one worth removing.
    """
    if not points:
        raise ValueError("cannot compute a frontier from an empty point set")
    ordered = sorted(points, key=lambda p: (p.cost, p.p99))
    frontier: list[PolicyPoint] = []
    best_p99 = float("inf")
    for point in ordered:
        # A tie is resolved in place rather than skipped: `ordered` sorts ties
        # by p99 ascending, so the first of a tied group is already its best
        # and later members are dominated -- but only exactly-equal costs sort
        # that way, and two dust-separated costs do not tie under `sorted`.
        # Comparing against the point actually on the frontier is what makes
        # the grouping independent of how the dust happened to fall.
        if frontier and math.isclose(
            point.cost, frontier[-1].cost, rel_tol=COST_TIE_RELATIVE_TOLERANCE
        ):
            if point.p99 < frontier[-1].p99:
                frontier[-1] = point
                best_p99 = point.p99
            continue
        if point.p99 < best_p99:
            frontier.append(point)
            best_p99 = point.p99
    return frontier


def iso_cost_budget(frontiers: dict[str, list[PolicyPoint]]) -> float:
    """The pre-registered iso-cost budget: the cheapest spend at which EVERY
    compared signal has at least one policy.

    `max` over each signal's cheapest frontier point. Two properties make this
    a rule rather than a number someone picked:

    - It is derivable from the sweep, not chosen after seeing it. Nothing about
      where the gap lands can influence it.
    - It BINDS. At exactly this budget the most expensive-floor signal has
      precisely one affordable policy, so the slice is a real constraint on at
      least one signal. The rule it replaces -- `min(cost) * 2`, written in the
      render script and pre-registered nowhere -- left every frontier fully
      affordable, which quietly turned "the inter-signal gap at iso-cost" into
      "the spread between each signal's UNCONSTRAINED best". That is a
      different quantity under the published name, and the more flattering one:
      it removes the cost axis from a comparison whose whole premise is a
      cost/latency tradeoff.

    Going any LOWER is not a stricter comparison, it is an undefined one:
    `gap_at_iso_cost` refuses a budget some signal cannot reach, because
    dropping that signal would report a spread between the survivors under the
    same name. This is therefore the lowest budget at which H3 has an answer at
    all.
    """
    if not frontiers:
        raise ValueError(
            "no frontiers, so there is no budget every signal can operate at; "
            "a gap needs at least two frontiers to be a spread between anything"
        )
    floors = {}
    for signal, frontier in frontiers.items():
        if not frontier:
            raise ValueError(
                f"the frontier for {signal!r} is empty, so it has no cheapest "
                "policy and there is no budget at which every signal can "
                "operate. An empty frontier is a finding about that signal, not "
                "a signal to compute the budget without"
            )
        floors[signal] = min(p.cost for p in frontier)
    return max(floors.values())


def _p99_at_cost(frontier: list[PolicyPoint], cost: float, signal: str) -> float:
    """The best p99 achievable at or below `cost` on this frontier.

    `signal` is carried in only so the refusal below can name it. Raising is
    deliberate and the alternative is worse: dropping a signal that cannot
    reach this budget would compute the H3 gap over the signals that remain,
    which is a spread between a DIFFERENT set of signals reported under the
    same name -- and it flatters the excluded one by never scoring it. "This
    signal can only operate above the iso-cost budget" is a publishable finding
    about that signal, so it is surfaced as an error the caller must decide
    about rather than absorbed into a number.
    """
    if not frontier:
        raise ValueError(
            f"the frontier for {signal!r} is empty; there is no p99 to read "
            "off it at any cost"
        )
    affordable = [p for p in frontier if p.cost <= cost]
    if not affordable:
        cheapest = min(p.cost for p in frontier)
        raise ValueError(
            f"no point on the {signal!r} frontier costs {cost} or less; its "
            f"cheapest policy is {cheapest} replica-seconds. That signal "
            "cannot operate at this iso-cost budget at all, which is a finding "
            "to publish about it, not a gap to compute without it -- excluding "
            "it would report a spread between the remaining signals under the "
            "same name and would flatter the one that was dropped"
        )
    return min(p.p99 for p in affordable)


def gap_at_iso_cost(
    frontiers: dict[str, list[PolicyPoint]],
    cost: float,
    expected: Iterable[str] = COMPARED_SIGNALS,
) -> float:
    """The H3 metric: p99 spread between the best and worst signal at equal spend.

    `expected` is the signal set the spread is claimed to be across, and a
    frontier dict missing any of it is refused rather than scored -- for the
    same reason `_p99_at_cost` refuses a signal that cannot reach the budget,
    and with the more dangerous consequence. A spread over what is left is a
    spread between a DIFFERENT set of signals reported under the same name, and
    here the arithmetic makes the error one-directional: a single-signal dict
    has `max == min`, so it returns 0.0, and `h3_verdict` reads a zero arm-C gap
    as a halving under `gap_c <= gap_a / 2`. An arm that LOST signals -- every
    run of them discarded by a pre-registered exclusion -- would therefore
    CONFIRM the artifact's headline out of missing data, while the arm that kept
    all three supplied the numerator. `figures.frontiers` has always refused to
    draw a chart missing a signal; until this guard, the number that chart is
    about had no equivalent.

    A caller comparing a deliberately narrower set passes it here, which is a
    statement in the code about what the returned number is a spread over --
    not a way around the check, since the narrowed set is then what is enforced.
    """
    if not frontiers:
        raise ValueError(
            "cannot compute a gap with no frontiers; a spread between zero "
            "signals is not zero, it is undefined"
        )
    if not math.isfinite(cost):
        raise ValueError(
            f"cost is {cost!r}, which is not finite; `p.cost <= cost` is False "
            "for every point under a NaN budget, so every frontier would look "
            "unaffordable, and an infinite budget silently slices at the most "
            "expensive policy each signal happens to have"
        )
    # Materialised once: `expected` is an Iterable, and a caller who passes a
    # generator would otherwise have it consumed by the set difference and find
    # the error message reporting an empty expected set.
    wanted = set(expected)
    missing = sorted(wanted - set(frontiers))
    if missing:
        raise ValueError(
            f"no frontier for signal(s) {missing}; this gap is published as the "
            f"p99 spread across {sorted(wanted)} and the ones present are "
            f"{sorted(frontiers)}. A spread over the survivors is a spread "
            "between a different set of signals reported under the same name, "
            "and it fails in the flattering direction: one signal left standing "
            "gives max == min == 0.0, which `h3_verdict` reads as the gap "
            "having halved. Pass `expected` to compare a deliberately narrower "
            "set, or publish the missing signals as the finding they are"
        )
    achieved = [_p99_at_cost(f, cost, signal) for signal, f in frontiers.items()]
    return max(achieved) - min(achieved)


def _take(point: "PolicyPoint", field: str, reps: tuple[int, ...]) -> list[float]:
    """This point's `field` values at the given REPETITION IDS.

    By id, not by position. The exclusion rules discard different runs for
    different policies, so position 3 is not repetition 3 once anything has
    been dropped -- and pairing on position would silently compare repetition 3
    of one signal against repetition 4 of another, which is precisely the
    cross-trace comparison the shared seed exists to prevent.

    Separate function so a test can prove one repetition list is shared across
    every policy in a draw -- see
    `test_the_gap_interval_resamples_one_index_list_for_every_policy`.
    """
    lookup = dict(zip(point.rep_indices, getattr(point, field), strict=True))
    # `r in lookup`: a policy that lost repetition r to a pre-registered
    # exclusion simply has no value for it in this draw, and contributes the
    # ones it does have. Requiring every policy to hold every drawn repetition
    # is what an intersection does, and on real sweeps it is ruinous -- one
    # frontier point that lost run 7 removes run 7 from EVERY policy, so ten
    # points each missing a few different runs collapse 30 repetitions to 19.
    # Pairing is preserved exactly where the data exists, which is the property
    # that matters: wherever two signals both have repetition r, they are
    # compared on the same arrival trace.
    return [lookup[r] for r in reps if r in lookup]


def _resample(point: "PolicyPoint", drawn: tuple[int, ...]) -> "PolicyPoint":
    """One bootstrap replicate of `point`, over the drawn repetition ids.

    Carries only the drawn repetitions this point HAS, so a policy that lost
    runs contributes fewer values to the replicate -- which is the honest
    reflection of its having fewer observations. The replicate's own
    `rep_indices` are positional: the draw is with replacement, so `drawn`
    repeats, and a resampled point's samples are no longer one-per-repetition
    and must not claim to be.
    """
    costs = _take(point, "cost_samples", drawn)
    p99s = _take(point, "p99_samples", drawn)
    return PolicyPoint(
        cost_samples=tuple(costs),
        p99_samples=tuple(p99s),
        signal=point.signal,
        scale_up_at=point.scale_up_at,
        scale_down_at=point.scale_down_at,
        rep_indices=tuple(range(len(p99s))),
    )


def gap_interval(
    frontiers: dict[str, list[PolicyPoint]],
    iterations: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
    expected: Iterable[str] = COMPARED_SIGNALS,
) -> dict:
    """A percentile-bootstrap interval on the iso-cost gap.

    Resamples REPETITION INDICES -- not policies, not latencies -- and uses ONE
    index list per draw across every policy in every signal. That is not an
    implementation convenience: repetition r of queue_depth and repetition r of
    in_flight_concurrency are replays of the same arrival trace (see
    `sweep._derive_seed`), and resampling each policy independently would break
    that correspondence and re-introduce precisely the traffic-to-traffic
    variance the shared seed was changed to cancel. The bootstrap would then
    report an interval wider than the design achieves, on a gap that is a
    paired difference.

    Each draw REBUILDS the frontiers and re-derives the budget from the
    resampled repetitions rather than reusing the observed ones. That is the
    expensive choice and it is the honest one: which policy sits on a frontier
    is itself estimated, and a bootstrap that holds the frontier fixed reports
    the uncertainty of a slice through a curve it pretends was known in
    advance. It also lets the winner's curse show up in the interval -- each
    frontier is a minimum over 17 to 19 noisy estimates, so the point gap is
    biased upward, and the resampled draws inherit that bias rather than hiding
    it. NOTE: this makes the bias VISIBLE, not corrected; a correction needs a
    held-out selection split and is not attempted here.

    Returns `{"point", "lo", "hi", "budget", "paired_repetitions"}`.
    `paired_repetitions` is the size of the repetition population drawn from.
    `point` and `budget` are the
    OBSERVED values, not bootstrap centres: the draws estimate spread, and
    reporting their centre would publish a different estimator from the one
    named.
    """
    if iterations <= 0:
        raise ValueError(f"iterations must be positive, got {iterations}")
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be strictly between 0 and 1, got {alpha}")

    wanted = set(expected)
    missing = sorted(wanted - set(frontiers))
    if missing:
        raise ValueError(
            f"no frontier for signal(s) {missing}; an interval on a spread "
            f"across {sorted(wanted)} cannot be computed from the ones present "
            f"({sorted(frontiers)}), and an interval on the wrong signal set "
            "reads as an interval on the headline"
        )

    all_points = [p for f in frontiers.values() for p in f]
    if not all_points:
        raise ValueError("every frontier is empty; there is no gap to put an interval on")

    # Resample over the repetition POPULATION -- every repetition any policy
    # kept -- rather than over the repetitions all of them kept in common.
    #
    # The intersection is the obvious construction and it is unusable here: one
    # frontier point that lost run 7 to a pre-registered exclusion removes run 7
    # from every OTHER policy too, so ten points each missing a few different
    # runs collapse 30 repetitions to 19 and the bootstrap refuses. Measured on
    # the real sweep, every signal's frontier had points with all 30 while the
    # intersection across them was 19-25.
    #
    # Drawing from the population and letting each policy contribute the drawn
    # repetitions it HAS keeps the property that actually matters: wherever two
    # signals both hold repetition r, they are compared on the same arrival
    # trace, which is the whole point of the shared seed. What it gives up is
    # balance -- a policy that lost runs contributes fewer values per draw --
    # and that is the honest reflection of its having fewer observations, the
    # same thing its point estimate already reflects.
    #
    # It assumes a discarded run is missing for reasons uncorrelated with the
    # value it would have had. That is NOT strictly true here: `no_scaling_action`
    # fires on traces where the policy never crossed its threshold, which are
    # the quieter traces. The bias this introduces is toward the policy looking
    # better than it is on the runs it kept, and it is the same bias the point
    # estimate carries -- the interval inherits it rather than creating it.
    population = set()
    for point in all_points:
        population |= set(point.rep_indices)
    reps_available = sorted(population)
    thin = [p for p in all_points if p.n < stats.MIN_BOOTSTRAP_SAMPLES]
    if thin:
        raise ValueError(
            f"{len(thin)} of {len(all_points)} frontier points have fewer than "
            f"{stats.MIN_BOOTSTRAP_SAMPLES} surviving repetitions (fewest: "
            f"{min(p.n for p in thin)}); below that floor a policy's resampled "
            "median is a handful of repeated values and the gap's interval "
            "inherits that. Check the per-signal discard counts: this is the "
            "pre-registered exclusions biting, and it is a finding about those "
            "policies rather than an interval to widen until it fits"
        )
    n = len(reps_available)

    observed_budget = iso_cost_budget(frontiers)
    point = gap_at_iso_cost(frontiers, cost=observed_budget, expected=wanted)

    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(iterations):
        drawn = tuple(reps_available[rng.randrange(n)] for _ in range(n))
        resampled = {
            signal: pareto_frontier([_resample(p, drawn) for p in f])
            for signal, f in frontiers.items()
        }
        budget = iso_cost_budget(resampled)
        draws.append(gap_at_iso_cost(resampled, cost=budget, expected=wanted))

    lo, hi = stats._percentile_interval(draws, alpha)
    return {
        "point": point,
        "lo": lo,
        "hi": hi,
        "budget": observed_budget,
        "paired_repetitions": n,
    }


def _validate_gap(label: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(
            f"{label} is {value!r}, which is not finite; a NaN gap compares "
            "False against the halving test, so H3 would be reported as "
            "refuted on the strength of a number that does not exist"
        )
    if value < 0:
        raise ValueError(
            f"{label} is {value!r}, which is negative; a gap is "
            "max(p99) - min(p99) across signals and cannot be below zero, so "
            "this is a caller bug -- and it lands on the flattering side: a "
            "negative arm-C gap satisfies the halving test automatically, and "
            "a negative arm-A gap would be mistaken for the vacuous-zero case "
            "below"
        )


def _halved(gap_a: float, gap_c: float) -> bool:
    """Did this shape's gap at least halve? `<=` because "at least half" is
    inclusive -- exactly half counts as holding."""
    return gap_c <= gap_a / 2


def h3_verdict(
    step_gap_a: float,
    step_gap_c: float,
    ramp_gap_a: float,
    ramp_gap_c: float,
    *,
    step_gap_a_interval: tuple[float, float] | None = None,
    ramp_gap_a_interval: tuple[float, float] | None = None,
) -> H3Verdict:
    """H3 holds only if the gap at least halves under BOTH spike shapes.

    Pre-registered that way because H4 already predicts the ramp's margins
    shrink, so a ramp-only halving is both the easier outcome and the less
    interesting one. A single-shape halving is published as partial rather than
    rounded up.

    A zero arm-A gap under either shape makes the verdict unevaluable rather
    than either true or false. `gap_c <= gap_a / 2` is satisfied by two zeros,
    so the plain arithmetic would report "the gap at least halved" for a shape
    where the signals were already indistinguishable under the SLOW
    distribution and stayed that way -- confirming the artifact's headline out
    of an absence of any effect to halve. That is the flattering direction of
    error, and the honest report is that H3 has no truth value on that shape.
    """
    for label, value in (
        ("step_gap_a", step_gap_a),
        ("step_gap_c", step_gap_c),
        ("ramp_gap_a", ramp_gap_a),
        ("ramp_gap_c", ramp_gap_c),
    ):
        # All four validated before any branch runs, so a NaN or negative gap
        # can never be mistaken for the vacuous-zero case below (`NaN <= 0` and
        # `-1.0 <= 0` would both be handled by that branch, one wrongly not
        # unevaluable and one wrongly unevaluable).
        _validate_gap(label, value)

    # "The gap at least halved" has no truth value when there was no gap under
    # arm A to halve. The original test for that was `gap_a == 0`, which is the
    # right IDEA and the wrong PREDICATE: a gap estimated around a true zero is
    # never exactly zero. Artifact 2's own original traffic model produced a
    # true gap of exactly zero and a MEASURED gap of 0.314, so the equality
    # walked straight past the one case it was written for and would have
    # returned an ordinary verdict on a quantity that has none.
    #
    # With an interval, the honest test is whether the arm-A gap is
    # distinguishable from zero at all. Without one the equality is kept, so
    # this is an added guard rather than a replaced one and a caller with no
    # interval is no worse off than before.
    unevaluable = []
    for shape, gap_a, interval in (
        ("step", step_gap_a, step_gap_a_interval),
        ("ramp", ramp_gap_a, ramp_gap_a_interval),
    ):
        if interval is not None and interval[0] <= 0.0:
            unevaluable.append((shape, "indistinguishable from zero", interval))
        elif interval is None and gap_a == 0:
            unevaluable.append((shape, "exactly zero", None))

    if unevaluable:
        detail = "; ".join(
            f"{shape}: the arm-A gap is {why}"
            + (f" (95% interval [{iv[0]:.4f}, {iv[1]:.4f}])" if iv else "")
            for shape, why, iv in unevaluable
        )
        return H3Verdict(
            False,
            False,
            f"H3 is not evaluable under {detail}. There was no inter-signal gap "
            "to halve, and `gap_c <= gap_a / 2` is satisfied by two zeros -- so "
            "reporting this as confirmed would confirm the headline out of an "
            "absence of any effect to measure",
            evaluable=False,
        )

    step_halved = _halved(step_gap_a, step_gap_c)
    ramp_halved = _halved(ramp_gap_a, ramp_gap_c)

    if step_halved and ramp_halved:
        return H3Verdict(True, False, "gap at least halved under both step and ramp")
    if step_halved or ramp_halved:
        shape = "step" if step_halved else "ramp"
        return H3Verdict(
            False,
            True,
            f"gap halved under {shape} only; published as a partial result, "
            "not as confirmation",
        )
    return H3Verdict(False, False, "gap did not halve under either shape")
