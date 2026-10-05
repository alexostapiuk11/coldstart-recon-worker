"""The ranking-blind regime screen: which offered load and SLO make the
three-way comparison defined at all.

Plan 1's sweep on placeholder inputs came out degenerate in both regimes
(amendment §14): swap sized to dedicate's M at every skew, partly because the
placeholder SLO was shorter than one swap. Artifact 2 met the same problem and
answered it with a screen whose question cannot be read as "strategy X is
better" (docs/findings-a2-degenerate-regime.md). This is that screen for
artifact 4.

Its question, per candidate: how many of the three strategies does each
evaluable grid point tell apart? A point scores the number of distinct sized
fleets among the three, minus one: 0 when all are equal (all dominated, or all
at dedicate's M), 2 when all three differ. The candidate's score is the sum.
It says whether the strategies can be told apart; it says nothing about which
is cheaper, so searching for a high score cannot smuggle in a preferred
winner. The highest score wins, and a tie goes to the earlier candidate in
`placement.step2`'s pre-registered order.

The first version counted points where the fleets were "not all equal". Run on
an example report, every candidate scored 12 of 12: co-locate's fully paired
fleet beat dedicate everywhere, which alone made every point count, while
swap sized to dedicate's M at most of them. A score every candidate maxes
out chooses nothing.

It runs on provisional inputs, because it must finish before the first
measurement run (amendment §12): the placeholder engines and
reconnaissance's own swap times. The SLO is a multiple of the swap median, so
the chosen multiple carries over to the measured swaps unchanged.
"""

from collections.abc import Callable, Sequence

from placement.evaluate import PointEvaluation
from placement.sizing import sized_fleet
from placement.step2 import SCREEN_OFFERED_GPUS, SCREEN_SLO_SWAP_MULTIPLES, SweepChoice

__all__ = ["choose", "run_screen", "score", "told_apart"]


def told_apart(sized: dict[str, int | None] | None) -> int:
    """How many strategies beyond the first this point tells apart: distinct
    sized fleets minus one, a dominated strategy counting as one value. 0 for
    a point that is not evaluable."""
    return 0 if sized is None else len(set(sized.values())) - 1


def score(evaluations: Sequence[PointEvaluation], slo: float) -> dict:
    rows = []
    for e in evaluations:
        sized = sized_fleet(e, list(range(e.repetitions)), slo)
        rows.append({"regime": e.point.regime, "s": e.point.s, "sized": sized,
                     "told_apart": told_apart(sized)})
    return {"score": sum(r["told_apart"] for r in rows),
            "evaluable": sum(r["sized"] is not None for r in rows), "points": rows}


def choose(scored: Sequence[dict]) -> dict:
    """The first candidate with the highest score: `max` keeps the first of
    equals, and `scored` is in pre-registered order."""
    if not scored:
        raise ValueError("no candidates were scored")
    return max(scored, key=lambda c: c["score"])


def run_screen(evaluate: Callable[[float], list[PointEvaluation]], swap_median_s: float) -> dict:
    """`evaluate(offered_gpus)` returns the grid's evaluations at that load.
    It is called once per offered load: the SLO only enters the scoring, so
    every SLO candidate is scored against the same evaluations."""
    scored = []
    for offered in SCREEN_OFFERED_GPUS:
        evaluations = evaluate(offered)
        for multiple in SCREEN_SLO_SWAP_MULTIPLES:
            slo = multiple * swap_median_s
            scored.append({"offered_gpus": offered, "slo_swap_multiple": multiple,
                           "slo_seconds": slo, **score(evaluations, slo)})
    best = choose(scored)
    return {"swap_median_s": swap_median_s, "candidates": scored,
            "chosen": {"offered_gpus": best["offered_gpus"],
                       "slo_swap_multiple": best["slo_swap_multiple"]},
            "choice": SweepChoice(best["offered_gpus"], best["slo_swap_multiple"])}
