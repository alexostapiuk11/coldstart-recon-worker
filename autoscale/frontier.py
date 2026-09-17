"""Pareto frontiers, the iso-cost slice, and H3's verdict.

Frontiers rather than points, because every policy has thresholds and whichever
set you publish decides the winner. Comparing frontiers is what makes the
comparison fair and robust to the objection that the loser was mistuned.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass

from autoscale.signals import SIGNALS

__all__ = [
    "COMPARED_SIGNALS",
    "H3Verdict",
    "PolicyPoint",
    "gap_at_iso_cost",
    "h3_verdict",
    "pareto_frontier",
]

# The signal set every published gap is a spread ACROSS. Taken from the signal
# registry rather than written out, so it is the same three the sweep runs and
# the same three `figures` refuses to draw without -- a fourth signal added to
# the registry is then compared, not silently left out of the headline.
COMPARED_SIGNALS = frozenset(SIGNALS)


@dataclass(frozen=True)
class PolicyPoint:
    cost: float  # replica-seconds
    p99: float  # seconds of request latency
    signal: str
    scale_up_at: float
    scale_down_at: float

    def __post_init__(self) -> None:
        """Frozen and validated for the same reason as `ServiceCurve` and
        `FleetState`: this record is built once and then compared thousands of
        times by `pareto_frontier`, which is nothing but comparisons.

        A NaN is the dangerous case and it is silent in both directions. A NaN
        `p99` fails `point.p99 < best_p99`, so the point is DROPPED from its own
        frontier -- an arm whose runs produced garbage would publish a frontier
        that simply omits them, looking like a sparser sweep rather than a
        broken one, and if every point were NaN the frontier would come back
        empty from a non-empty input, which `pareto_frontier`'s own emptiness
        guard would then never see. A NaN `cost` fails `p.cost <= cost` in
        `_p99_at_cost`, so the point is invisible at every iso-cost slice. An
        infinite cost passes every comparison as an ordinary extreme value and
        would sit on the frontier as an affordable-at-infinity point.
        """
        for field_name, value in (
            ("cost", self.cost),
            ("p99", self.p99),
            ("scale_up_at", self.scale_up_at),
            ("scale_down_at", self.scale_down_at),
        ):
            if not math.isfinite(value):
                raise ValueError(
                    f"{field_name} is {value!r}, which is not finite; a NaN "
                    "compares False against every ordering test in "
                    "pareto_frontier and _p99_at_cost, so the point would be "
                    "silently dropped from its own frontier instead of "
                    "raising here, and an infinity would sit on the frontier "
                    "as an ordinary extreme value"
                )
        # Both axes are physical readings with a floor: replica-seconds is an
        # integral of a non-negative replica count, latency is a duration. A
        # negative one is a bookkeeping bug, and on these axes -- where lower
        # is better on both -- it does not read as a small value but as a
        # WINNING one, dominating every honest point on the frontier.
        for field_name, value in (("cost", self.cost), ("p99", self.p99)):
            if value < 0:
                raise ValueError(
                    f"{field_name} is {value!r}, which is negative; lower is "
                    "better on both frontier axes, so a negative value does "
                    "not read as a small one but as a point that dominates "
                    "every honest policy in the sweep"
                )


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


def pareto_frontier(points: list[PolicyPoint]) -> list[PolicyPoint]:
    """Non-dominated points, ascending by cost. Lower cost and lower p99 are
    both better, so a point is dominated when another is at least as good on
    both axes."""
    if not points:
        raise ValueError("cannot compute a frontier from an empty point set")
    ordered = sorted(points, key=lambda p: (p.cost, p.p99))
    frontier: list[PolicyPoint] = []
    best_p99 = float("inf")
    for point in ordered:
        if point.p99 < best_p99:
            frontier.append(point)
            best_p99 = point.p99
    return frontier


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
    step_gap_a: float, step_gap_c: float, ramp_gap_a: float, ramp_gap_c: float
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

    unevaluable = [
        shape for shape, gap_a in (("step", step_gap_a), ("ramp", ramp_gap_a)) if gap_a == 0
    ]
    if unevaluable:
        return H3Verdict(
            False,
            False,
            "H3 is not evaluable under "
            + " and ".join(unevaluable)
            + ": the arm-A gap was zero, so there was no inter-signal gap to "
            "halve. Reported as unevaluable rather than confirmed, because "
            "`gap_c <= gap_a / 2` is satisfied by two zeros",
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
