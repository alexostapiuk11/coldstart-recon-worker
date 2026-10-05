"""The sweep's grid, and its evaluation across worker processes.

Moved here unchanged from `scripts/a4_sweep.py` so that the ranking-blind
screen (`scripts/a4_screen.py`) builds its grid and evaluates it exactly as the
sweep does. A screen that sized its runs or seeded its pilot differently would
be screening a different experiment.
"""

from concurrent.futures import ProcessPoolExecutor

from placement.design import Design
from placement.evaluate import GridPoint, PointEvaluation, Scenario, evaluate_point
from placement.resample import EmpiricalDistribution
from placement.runlength import pilot_window
from placement.sim import Engines
from placement.tails import P99_FLOOR
from placement.traffic import decile_of, zipf_shares

__all__ = ["PILOT_SEED_OFFSET", "evaluate_grid", "grid"]

# The pilot draws from its own seed range, so it never shares a stream with a
# repetition it is sizing.
PILOT_SEED_OFFSET = 1_000_003


def grid(design: Design, scenario: Scenario) -> list[GridPoint]:
    """One grid point per (regime, skew), each with the window its pilot found."""
    deciles = decile_of(design.n_models)
    points = []
    for regime in design.regimes:
        for s in design.skews:
            shares = zipf_shares(design.n_models, s)
            coldest = min(sum(sh for sh, d in zip(shares, deciles) if d == k) for k in range(10))
            # Start the pilot at half the break-even window; it only grows.
            start = 0.5 * P99_FLOOR / (coldest * scenario.total_rate)
            window = pilot_window(
                shares, deciles, regime, scenario.total_rate, design.repetitions,
                design.mean_burst, design.duty, design.pilot_traces,
                seed=design.seed + PILOT_SEED_OFFSET, start=start,
            )
            points.append(GridPoint(s=s, regime=regime, until=design.warmup + window))
    return points


def evaluate_grid(
    points: list[GridPoint],
    scenario: Scenario,
    engines: Engines,
    swap_time: EmpiricalDistribution,
    repetitions: int,
    seed: int,
    slo: float | None,
    workers: int,
) -> list[PointEvaluation]:
    """`evaluate_point` at every grid point, one process per point."""
    n = len(points)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(evaluate_point, points, [scenario] * n, [engines] * n,
                             [swap_time] * n, [repetitions] * n, [seed] * n, [slo] * n))
