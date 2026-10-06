"""H1, H2 and H4, operationalised after the simulator's frontiers were seen.

The pre-registration states H1, H2 and H4 in words only. These definitions
were written on 2026-10-05, after the x1.00 frontiers had been printed by
the exploratory sensitivity run, and were signed by the owner before this
module computed anything (publication plan, Task 0). The post says so beside
every verdict, and every verdict is on an UNVALIDATED simulator.

Each function takes frontiers per signal (`{signal: [PolicyPoint, ...]}`) for
one sweep. "Reached p99" is the iso-cost slice the gap uses: the best median
p99 a signal's frontier reaches at or under the budget.

Only `COMPARED_SIGNALS` take part. A sweep's frontier dict can also carry the
`utilization_throughput` sensitivity arm, and letting it in would change the
published numbers without saying so: it would move `iso_cost_budget` (a
costlier floor raises the budget for everyone), and under H1 its points would
have to be dominated too. H2 is a claim about the headline utilisation signal;
the sensitivity arm is reported beside it, not folded into it. Rejected
alternative: computing over whatever signals the dict holds, which is what
`iso_cost_budget` itself does and is correct only because the gap's caller
passes it the three. A compared signal that is absent is refused (see
`_compared`) rather than scored over the survivors, for the reason
`gap_at_iso_cost` gives.
"""

import math

from autoscale.frontier import (
    COMPARED_SIGNALS,
    COST_TIE_RELATIVE_TOLERANCE,
    PolicyPoint,
    _p99_at_cost,
    iso_cost_budget,
)

__all__ = ["TIE_SECONDS", "h1_holds_on", "h2_worst_on", "h4_holds_on", "ranking", "reached_p99"]

# Two signals whose reached p99 differ by no more than a millisecond are tied.
TIE_SECONDS = 0.001


def _compared(frontiers: dict[str, list[PolicyPoint]]) -> dict[str, list[PolicyPoint]]:
    """The frontiers of the compared signals, refusing a dict that lacks one."""
    missing = sorted(COMPARED_SIGNALS - set(frontiers))
    if missing:
        raise ValueError(
            f"no frontier for signal(s) {missing}; H1, H2 and H4 are claims "
            f"about all of {sorted(COMPARED_SIGNALS)} and the ones present are "
            f"{sorted(frontiers)}. Scoring the survivors would report a verdict "
            "about a different set of signals under the same name, so the "
            "verdict is refused instead of computed"
        )
    return {s: frontiers[s] for s in COMPARED_SIGNALS}


def reached_p99(frontiers: dict[str, list[PolicyPoint]], budget: float) -> dict[str, float]:
    """Each compared signal's best median p99 at or under `budget`.

    Calls `autoscale.frontier._p99_at_cost`, the function `gap_at_iso_cost`
    itself reads, so this is the gap's own slice by construction and inherits
    its refusal: a signal that cannot reach the budget raises with the
    explanation of why that is a finding, not a gap to compute without it.
    Rejected alternative: a local `min(p.p99 for p in f if p.cost <= budget)`,
    which would silently diverge if the gap's slice rule ever changed and, for
    an unreachable budget, would raise a bare "min() arg is an empty sequence"
    that says nothing about which signal or what it means.
    """
    return {s: _p99_at_cost(f, budget, s) for s, f in _compared(frontiers).items()}


def _dominates(a: PolicyPoint, b: PolicyPoint) -> bool:
    """a is no costlier and no slower than b, and strictly better on one axis.

    Costs within `COST_TIE_RELATIVE_TOLERANCE` are EQUAL, the tolerance
    `pareto_frontier` already applies to cost ties: replica-seconds are float
    sums whose last digits are accumulation-order dust, and an exact `<=`
    would let that dust decide whether a point is dominated (and so whether H1
    holds). Rejected: exact comparison, which disagrees with the frontier
    about which points tie.
    """
    same_cost = math.isclose(a.cost, b.cost, rel_tol=COST_TIE_RELATIVE_TOLERANCE)
    cost_no_worse = a.cost <= b.cost or same_cost
    cost_better = a.cost < b.cost and not same_cost
    return cost_no_worse and a.p99 <= b.p99 and (cost_better or a.p99 < b.p99)


def h1_holds_on(frontiers: dict[str, list[PolicyPoint]]) -> bool:
    """Every queue-depth and utilisation frontier point is weakly dominated by an
    in-flight one (cost <= and p99 <= on medians, at least one strictly).

    The signed definition requires "at least one strictly", so a point that
    ties an in-flight point on BOTH axes is NOT dominated and makes H1 False:
    an identical outcome is no evidence that in-flight concurrency does better,
    and a hypothesis called "dominates" should not hold on a draw. The
    consequence is that H1 can fail on a signal that merely matches in-flight
    exactly, which is the conservative direction for a claim of dominance.

    Rejected: comparing only at the iso-cost slice, which is H3's measure; H1
    says "dominates on the frontier", which is the whole curve, so each point
    of the others may be dominated by a different in-flight point.
    """
    f = _compared(frontiers)
    inflight = f["in_flight_concurrency"]
    others = [p for s in ("queue_depth", "utilization") for p in f[s]]
    return all(any(_dominates(a, b) for a in inflight) for b in others)


def h2_worst_on(frontiers: dict[str, list[PolicyPoint]]) -> bool:
    """Utilisation's reached p99 at the budget is the highest, by more than a tie."""
    f = _compared(frontiers)
    r = reached_p99(f, iso_cost_budget(f))
    return all(r["utilization"] > r[s] + TIE_SECONDS for s in r if s != "utilization")


def ranking(frontiers: dict[str, list[PolicyPoint]]) -> list[list[str]]:
    """Signals from best to worst reached p99 at the budget; ties grouped.

    A tie is chained from the previous group's last member, so a run of signals
    each within a millisecond of the next forms one group. Rejected: comparing
    against the group's first member, which would split a chain whose ends are
    just over a millisecond apart even though no neighbours are distinguishable.
    """
    f = _compared(frontiers)
    r = reached_p99(f, iso_cost_budget(f))
    groups: list[list[str]] = []
    for s in sorted(r, key=lambda k: (r[k], k)):
        if groups and abs(r[s] - r[groups[-1][-1]]) <= TIE_SECONDS:
            groups[-1].append(s)
        else:
            groups.append([s])
    return [sorted(g) for g in groups]


def _gap(frontiers: dict[str, list[PolicyPoint]]) -> float:
    f = _compared(frontiers)
    r = reached_p99(f, iso_cost_budget(f))
    return max(r.values()) - min(r.values())


def h4_holds_on(step: dict[str, list[PolicyPoint]], ramp: dict[str, list[PolicyPoint]]) -> bool:
    """Same ranking on both shapes, and a smaller gap on the ramp.

    Each shape is sliced at its OWN iso-cost budget, as H3's gap is per sweep;
    a shared budget would be undefined whenever one shape's cheapest floor lay
    above the other's frontier.
    """
    return ranking(step) == ranking(ramp) and _gap(ramp) < _gap(step)
