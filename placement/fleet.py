"""Placements: which GPU holds which model, per strategy and fleet size.

The rules are the amendment's §7:

- Hot models are identified once, by one rule, and get pinned solo GPUs in
  every strategy. Letting only some strategies replicate would make the others
  infeasible at high skew by construction.
- The strategies differ only in how the tail is placed.
- Each strategy is a family of placements ordered by GPU count M. Dedicate has
  one member. Swap grows its shared pool one GPU at a time. Co-locate starts
  fully paired and un-pairs its busiest pair per added GPU. Both of the latter
  reach dedicate's capacity at dedicate's M, which bounds the sizing search.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["STRATEGIES", "Gpu", "Placement", "family", "hot_allocation"]

STRATEGIES = ("dedicate", "swap", "colocate")
_ONE_MODEL = ("pinned", "solo", "pool")


@dataclass(frozen=True)
class Gpu:
    """`kind` is pinned (a hot model), solo (one tail model), pair (two tail
    models co-located), or pool (a swap GPU; `models` is its first resident)."""

    kind: str
    models: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "models", tuple(self.models))
        if self.kind in _ONE_MODEL:
            if len(self.models) != 1:
                raise ValueError(f"a {self.kind} GPU holds exactly one model, got {self.models}")
        elif self.kind == "pair":
            if len(self.models) != 2 or self.models[0] == self.models[1]:
                raise ValueError(f"a pair GPU holds two distinct models, got {self.models}")
        else:
            raise ValueError(f"unknown GPU kind {self.kind!r}")


@dataclass(frozen=True)
class Placement:
    strategy: str
    gpus: tuple[Gpu, ...]
    # The tail models the swap pool serves. Empty for dedicate and co-locate.
    pool_models: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "gpus", tuple(self.gpus))
        object.__setattr__(self, "pool_models", tuple(self.pool_models))
        if self.strategy not in STRATEGIES:
            raise ValueError(f"unknown strategy {self.strategy!r}")
        pool = [g for g in self.gpus if g.kind == "pool"]
        if bool(pool) != bool(self.pool_models):
            raise ValueError(
                "pool GPUs and pool models come together: a pool with no models "
                "idles, and pool models with no pool GPU are never served"
            )
        if pool and self.strategy != "swap":
            raise ValueError("only the swap strategy has a pool")
        residents = [g.models[0] for g in pool]
        if len(set(residents)) != len(residents) or not set(residents) <= set(self.pool_models):
            raise ValueError(
                "each pool GPU starts with a distinct pool model; a model resident "
                "twice breaks swap's at-most-once rule"
            )
        pinned = {m for g in self.gpus if g.kind == "pinned" for m in g.models}
        placed = [m for g in self.gpus if g.kind in ("solo", "pair") for m in g.models]
        if len(set(placed)) != len(placed):
            raise ValueError("a tail model is placed on more than one GPU")
        overlap = (set(placed) | set(self.pool_models)) & pinned
        if overlap or set(placed) & set(self.pool_models):
            raise ValueError("a model is placed in two roles at once")

    @property
    def m(self) -> int:
        return len(self.gpus)

    @property
    def served(self) -> frozenset[int]:
        return frozenset(m for g in self.gpus for m in g.models) | frozenset(self.pool_models)


def hot_allocation(
    shares: Sequence[float], offered_gpus: float, hot_fraction: float, peak_factor: float = 1.0
) -> dict[int, int]:
    """Pinned GPUs per hot model.

    `offered_gpus` is the total offered load in units of one GPU's measured
    saturation. A model whose load exceeds `hot_fraction` of one GPU is hot and
    gets ceil(load / hot_fraction) pinned GPUs, so none of its GPUs is asked to
    run above `hot_fraction` of saturation.

    `peak_factor` scales each model's average load to the load the rule sizes
    for. It is 1 in the spread regime. In the bursty regime it is 1 / duty: a
    model receives all its traffic while ON, so its load then is its average
    divided by duty, and a GPU sized for the average is asked to carry five
    times that during a burst at duty 0.2 (amendment §14, decided 2026-10-04).
    The rule is still one rule for all three strategies.
    """
    if not math.isfinite(offered_gpus) or offered_gpus <= 0:
        raise ValueError(f"offered_gpus must be finite and positive, got {offered_gpus!r}")
    if not (0.0 < hot_fraction <= 1.0):
        raise ValueError(
            f"hot_fraction must be in (0, 1], got {hot_fraction!r}; above 1 a hot "
            "model's GPU would be planned past saturation"
        )
    if not math.isfinite(peak_factor) or peak_factor < 1.0:
        raise ValueError(
            f"peak_factor must be finite and at least 1, got {peak_factor!r}; below 1 "
            "the rule would size a model for less than its average load"
        )
    hot = {}
    for model, share in enumerate(shares):
        load = share * offered_gpus * peak_factor
        if load > hot_fraction:
            hot[model] = math.ceil(load / hot_fraction)
    return hot


def family(strategy: str, shares: Sequence[float], hot: dict[int, int]) -> tuple[Placement, ...]:
    """Every placement the sizing search considers for `strategy`, by ascending M."""
    pinned = tuple(Gpu("pinned", (m,)) for m in sorted(hot) for _ in range(hot[m]))
    tail = [m for m in range(len(shares)) if m not in hot]  # hottest first
    if strategy == "dedicate" or not tail:
        return (Placement(strategy, pinned + tuple(Gpu("solo", (m,)) for m in tail)),)
    if strategy == "swap":
        return tuple(
            Placement(
                "swap",
                pinned + tuple(Gpu("pool", (m,)) for m in tail[:size]),
                pool_models=tuple(tail),
            )
            for size in range(1, len(tail) + 1)
        )
    if strategy == "colocate":
        half = len(tail) // 2
        # Busiest tail model with the least busy, and inward. This keeps each
        # busier model's neighbour quiet; it does not balance pair loads.
        pairs = [(tail[i], tail[-1 - i]) for i in range(half)]
        leftover = (tail[half],) if len(tail) % 2 else ()
        # Un-pair the busiest remaining pair first.
        pairs.sort(key=lambda p: -(shares[p[0]] + shares[p[1]]))
        placements = []
        for split in range(len(pairs) + 1):
            solos = [m for pair in pairs[:split] for m in pair] + list(leftover)
            gpus = (
                pinned
                + tuple(Gpu("pair", pair) for pair in pairs[split:])
                + tuple(Gpu("solo", (m,)) for m in sorted(solos))
            )
            placements.append(Placement("colocate", gpus))
        return tuple(placements)
    raise ValueError(f"unknown strategy {strategy!r}")
