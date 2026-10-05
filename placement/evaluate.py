"""Evaluate one grid point: every configuration of every strategy, every repetition.

Everything the sizing and the crossover interval need is computed here once.
Sizing picks the cheapest configuration that meets the SLO, and the bootstrap
re-sizes inside every draw, so both need the per-decile p99 of every
(configuration, repetition), not only the winner's.

Common random numbers: repetition r is the same trace for every strategy and
every configuration, and the same swap-duration stream. Neither the strategy
nor the configuration is in the seed key, so strategy differences are paired
within a repetition and traffic variance cancels, as in artifact 2's
`sweep._derive_seed`.
"""

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from placement.fleet import STRATEGIES, family, hot_allocation
from placement.resample import EmpiricalDistribution
from placement.sim import Engines, simulate
from placement.tails import P99_FLOOR, decile_counts, decile_p99s
from placement.traffic import bursty_trace, decile_of, spread_trace, zipf_shares

__all__ = [
    "REGIMES",
    "ConfigOutcome",
    "GridPoint",
    "PointEvaluation",
    "Scenario",
    "dump_evaluations",
    "evaluate_point",
    "load_evaluations",
]

REGIMES = ("spread", "bursty")


@dataclass(frozen=True)
class Scenario:
    """Everything the pre-registration fixes that is not a grid coordinate.

    `offered_gpus` is total load in units of one GPU's saturation, and
    `saturation_rps` is that saturation in requests per second, computed from
    the measured solo curve by the caller.
    """

    n_models: int
    offered_gpus: float
    saturation_rps: float
    hot_fraction: float
    warmup: float
    mean_burst: float
    duty: float

    @property
    def total_rate(self) -> float:
        return self.offered_gpus * self.saturation_rps


@dataclass(frozen=True)
class GridPoint:
    """One cell of the sweep. `until` is warm-up plus the measured window,
    which the run-length pilot sets per grid point."""

    s: float
    regime: str
    until: float

    def __post_init__(self) -> None:
        if self.regime not in REGIMES:
            raise ValueError(f"unknown regime {self.regime!r}")
        if not math.isfinite(self.until) or self.until <= 0:
            raise ValueError(f"until must be finite and positive, got {self.until!r}")


@dataclass(frozen=True)
class ConfigOutcome:
    """One configuration's results, one entry per repetition."""

    strategy: str
    m: int
    decile_p99s: tuple[tuple[float | None, ...], ...]
    swaps: tuple[int, ...]
    extrapolated: tuple[int, ...]


@dataclass(frozen=True)
class PointEvaluation:
    point: GridPoint
    # Per strategy, its configurations in ascending M.
    outcomes: dict[str, tuple[ConfigOutcome, ...]]
    # Post-warm-up requests per decile, one tuple per repetition. The same for
    # every configuration, because the trace is.
    counts: tuple[tuple[int, ...], ...]

    @property
    def repetitions(self) -> int:
        return len(self.counts)

    @property
    def floor_met(self) -> bool:
        """Every decile cleared the p99 floor in every repetition."""
        return all(c >= P99_FLOOR for rep in self.counts for c in rep)


def _seed(seed: int, point: GridPoint, rep: int, stream: str) -> int:
    """Stable across processes, unlike `hash()`; see artifact 2's
    `sweep._derive_seed` for why that matters."""
    key = f"{seed}|{point.s!r}|{point.regime}|{point.until!r}|{rep}|{stream}".encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")


def evaluate_point(
    point: GridPoint,
    scenario: Scenario,
    engines: Engines,
    swap_time: EmpiricalDistribution,
    repetitions: int,
    seed: int,
) -> PointEvaluation:
    shares = zipf_shares(scenario.n_models, point.s)
    deciles = decile_of(scenario.n_models)
    hot = hot_allocation(shares, scenario.offered_gpus, scenario.hot_fraction)
    families = {strategy: family(strategy, shares, hot) for strategy in STRATEGIES}
    per_config: dict[str, list[dict[str, list]]] = {
        strategy: [{"p99s": [], "swaps": [], "extrapolated": []} for _ in configs]
        for strategy, configs in families.items()
    }
    counts = []
    for rep in range(repetitions):
        rng = random.Random(_seed(seed, point, rep, "trace"))
        if point.regime == "spread":
            trace = spread_trace(shares, scenario.total_rate, point.until, rng)
        else:
            trace = bursty_trace(
                shares, scenario.total_rate, point.until, scenario.mean_burst, scenario.duty, rng
            )
        counts.append(decile_counts([m for t, m in trace if t >= scenario.warmup], deciles))
        for strategy, configs in families.items():
            for i, placement in enumerate(configs):
                result = simulate(
                    trace,
                    placement,
                    engines,
                    swap_time,
                    scenario.warmup,
                    random.Random(_seed(seed, point, rep, "swap")),
                )
                slot = per_config[strategy][i]
                slot["p99s"].append(decile_p99s(result, deciles))
                slot["swaps"].append(result.swaps)
                slot["extrapolated"].append(result.extrapolated)
    outcomes = {
        strategy: tuple(
            ConfigOutcome(
                strategy=strategy,
                m=placement.m,
                decile_p99s=tuple(slot["p99s"]),
                swaps=tuple(slot["swaps"]),
                extrapolated=tuple(slot["extrapolated"]),
            )
            for placement, slot in zip(families[strategy], per_config[strategy], strict=True)
        )
        for strategy in STRATEGIES
    }
    return PointEvaluation(point=point, outcomes=outcomes, counts=tuple(counts))


def dump_evaluations(path: Path, evaluations: list[PointEvaluation]) -> None:
    """Cache to JSON, so re-drawing a table does not re-run a sweep."""
    path.write_text(json.dumps([asdict(e) for e in evaluations]))


def load_evaluations(path: Path) -> list[PointEvaluation]:
    loaded = []
    for raw in json.loads(path.read_text()):
        outcomes = {
            strategy: tuple(
                ConfigOutcome(
                    strategy=o["strategy"],
                    m=o["m"],
                    decile_p99s=tuple(tuple(rep) for rep in o["decile_p99s"]),
                    swaps=tuple(o["swaps"]),
                    extrapolated=tuple(o["extrapolated"]),
                )
                for o in configs
            )
            for strategy, configs in raw["outcomes"].items()
        }
        loaded.append(
            PointEvaluation(
                point=GridPoint(**raw["point"]),
                outcomes=outcomes,
                counts=tuple(tuple(rep) for rep in raw["counts"]),
            )
        )
    return loaded
