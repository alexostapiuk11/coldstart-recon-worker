"""Sizing S and N from the pilot, and the cost of the campaign (amendment §4d, §8).

The effective sample size of S scenarios x N repetitions with intra-scenario
correlation rho is S*N / (1 + (N - 1)*rho). It approaches S/rho as N grows, so
past some N another repetition buys almost nothing. The rule implemented here:
the smallest N that reaches 95% of that limit, between the floor and the cap.
S is every included scenario, because under a high rho the information is in S.

Lowering N to fit the approved budget is not done here. That is
pre-registration step 2's decision, under amendment §8's cut order; this module
supplies the 95% rule, the floor and the cap, and the cost table it is checked
against.
"""

import math
from dataclasses import dataclass

TARGET_FRACTION = 0.95


def icc(groups: list[list[int]]) -> float:
    """One-way ANOVA estimator of the intra-class correlation for 0/1
    outcomes, one group per scenario. Unequal group sizes use the usual n0
    correction. Clamped to [0, 1]: a negative estimate means no clustering.

    When every outcome is identical (a pilot cell that is 100% correct, say)
    there is no variance to apportion and rho is undefined; it is treated as 1,
    which sends `reps_for` to the floor N. When every group has size 1 there is
    no within-group information at all and the call is refused."""
    groups = [g for g in groups if g]
    k = len(groups)
    if k < 2:
        raise ValueError("an ICC needs at least two scenarios")
    sizes = [len(g) for g in groups]
    total = sum(sizes)
    if total == k:
        raise ValueError("an ICC needs at least one scenario with two or more repetitions")
    grand = sum(sum(g) for g in groups) / total
    ssb = sum(n * (sum(g) / n - grand) ** 2 for g, n in zip(groups, sizes))
    ssw = sum(sum((x - sum(g) / len(g)) ** 2 for x in g) for g in groups)
    msb = ssb / (k - 1)
    msw = ssw / (total - k) if total > k else 0.0
    n0 = (total - sum(n * n for n in sizes) / total) / (k - 1)
    denom = msb + (n0 - 1) * msw
    if denom == 0:
        return 1.0  # all outcomes identical: rho undefined, treated as 1 (see docstring)
    return min(1.0, max(0.0, (msb - msw) / denom))


def effective_n(s: int, n: int, rho: float) -> float:
    return s * n / (1 + (n - 1) * rho)


def reps_for(rho: float, n_floor: int, n_cap: int) -> int:
    """Smallest N with N*rho / (1 + (N-1)*rho) >= TARGET_FRACTION, clamped."""
    if rho <= 0:
        return n_cap
    need = TARGET_FRACTION * (1 - rho) / ((1 - TARGET_FRACTION) * rho)
    return max(n_floor, min(n_cap, math.ceil(need)))


@dataclass(frozen=True)
class Line:
    name: str
    calls: int
    usd_per_call: float

    @property
    def usd(self) -> float:
        return self.calls * self.usd_per_call


def total(lines: list[Line]) -> float:
    return sum(line.usd for line in lines)


def table(lines: list[Line], contingency: float = 0.25) -> str:
    rows = ["| component | calls | USD per call | USD |", "|---|---|---|---|"]
    rows += [f"| {x.name} | {x.calls:,} | {x.usd_per_call:.5f} | {x.usd:.2f} |" for x in lines]
    t = total(lines)
    rows.append(f"| **total** | | | **{t:.2f}** |")
    rows.append(f"| with {contingency:.0%} contingency | | | {t * (1 + contingency):.2f} |")
    return "\n".join(rows)
