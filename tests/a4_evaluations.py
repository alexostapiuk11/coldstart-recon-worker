"""Hand-built evaluations for plan 3's analysis, cost-file and figure tests.

Not a test module. Every configuration's numbers are chosen so the sizing is
known in advance: a configuration "meets" an SLO of 10 s when its p99s are 5 s
and misses it when they are 50 s.
"""

from placement.design import Design
from placement.evaluate import ConfigOutcome, GridPoint, PointEvaluation
from placement.money import Assumptions

REPS = 20
SLO = 10.0
RATE = Assumptions(gpu_hourly_rate=0.69, provenance="test rate")
DESIGN = Design(n_models=20, offered_gpus=2.0, hot_fraction=0.7, warmup=100.0, mean_burst=120.0,
                duty=0.2, skews=(0.6, 1.0), regimes=("spread", "bursty"), repetitions=REPS,
                slo_seconds=SLO, pilot_traces=1200, seed=17, preregistered=True)


def config(strategy, m, *, cold_p99=5.0, warm_p99=5.0, aggregate=4.0, breach=0.0, hits=95,
           swaps=0, jitter=True):
    """A configuration whose coldest decile has p99 `cold_p99` and the others
    `warm_p99`, varying by a few hundredths across repetitions so intervals
    have width."""
    def wobble(x, r):
        return x + (0.01 * (r % 5) if jitter else 0.0)

    return ConfigOutcome(
        strategy=strategy, m=m,
        decile_p99s=tuple((wobble(warm_p99, r),) * 9 + (wobble(cold_p99, r),) for r in range(REPS)),
        swaps=(swaps,) * REPS, extrapolated=(0,) * REPS,
        aggregate_p99s=tuple(wobble(aggregate, r) for r in range(REPS)),
        window_swaps=(swaps,) * REPS,
        hits=(hits,) * REPS, requests=(100,) * REPS,
        decile_breach=tuple((0.0,) * 9 + (breach,) for _ in range(REPS)),
    )


def evaluation(s, regime, outcomes, *, counts=600):
    return PointEvaluation(point=GridPoint(s, regime, 3700.0), outcomes=outcomes,
                           counts=((counts,) * 10,) * REPS)


def _family(strategy, ms, meets_from, passing=None, **failing):
    """Every M from `ms`, as a real family has: configurations from
    `meets_from` meet the SLO with `passing`'s numbers, and those below miss
    it with `failing`'s."""
    return tuple(config(strategy, m, **(passing or {})) if m >= meets_from
                 else config(strategy, m, **failing) for m in ms)


def swap_cheap(s, regime):
    """Dedicate at 10; swap meets the SLO from 6; co-locate only at 10. Swap at
    4 and 5 meets the aggregate but not the coldest decile."""
    return evaluation(s, regime, {
        "dedicate": (config("dedicate", 10),),
        "swap": _family("swap", range(4, 11), 6, {"swaps": 12, "hits": 90}, cold_p99=50.0,
                        breach=0.3, swaps=40),
        "colocate": _family("colocate", range(7, 11), 10, cold_p99=50.0, warm_p99=50.0,
                            aggregate=50.0),
    })


def dedicate_only(s, regime):
    """Swap and co-locate meet the SLO only at dedicate's 10: a three-way tie."""
    return evaluation(s, regime, {
        "dedicate": (config("dedicate", 10),),
        "swap": _family("swap", range(4, 11), 10, cold_p99=50.0, warm_p99=50.0, aggregate=50.0),
        "colocate": _family("colocate", range(7, 11), 10, cold_p99=50.0, warm_p99=50.0,
                            aggregate=50.0),
    })


def swap_dominated(s, regime):
    """Swap misses the SLO even at dedicate's 10."""
    return evaluation(s, regime, {
        "dedicate": (config("dedicate", 10),),
        "swap": _family("swap", range(4, 11), 11, cold_p99=50.0, warm_p99=50.0, aggregate=50.0),
        "colocate": _family("colocate", range(7, 11), 10, cold_p99=50.0, warm_p99=50.0,
                            aggregate=50.0),
    })


def sweep():
    """Spread: a three-way tie at s=0.6, swap at s=1.0. Bursty: swap at both."""
    return [dedicate_only(0.6, "spread"), swap_cheap(1.0, "spread"),
            swap_cheap(0.6, "bursty"), swap_cheap(1.0, "bursty")]


SKEWS = (0.6, 0.8, 1.0, 1.25, 1.5, 2.0)


def _point(s, regime, swap_from, colocate_from):
    """Swap meets the SLO from `swap_from` GPUs, co-locate from
    `colocate_from`; both families run up to dedicate's 12. Latency falls as
    the fleet grows, so the aggregate p99 has some shape to draw."""
    def family(strategy, ms, meets_from):
        return tuple(
            config(strategy, m, cold_p99=5.0 + (12 - m) * 0.4, warm_p99=3.0 + (12 - m) * 0.2,
                   aggregate=2.5 + (12 - m) * 0.15 + s, hits=90, swaps=20 - m)
            if m >= meets_from else
            config(strategy, m, cold_p99=40.0, breach=0.25, aggregate=3.0 + s, swaps=60)
            for m in ms)

    return evaluation(s, regime, {
        "dedicate": (config("dedicate", 12, aggregate=2.0 + s, cold_p99=4.0),),
        "swap": family("swap", range(5, 13), swap_from),
        "colocate": family("colocate", range(8, 13), colocate_from),
    })


def rich_sweep():
    """Six skews per regime, for drawing figures with some shape to them:
    swap thrashes at low skew in the spread regime and wins earlier when
    arrivals are bursty."""
    spread = {0.6: (13, 12), 0.8: (12, 11), 1.0: (11, 10), 1.25: (9, 10), 1.5: (7, 10), 2.0: (6, 9)}
    bursty = {0.6: (11, 11), 0.8: (9, 10), 1.0: (8, 10), 1.25: (7, 10), 1.5: (6, 9), 2.0: (5, 9)}
    return ([_point(s, "spread", *spread[s]) for s in SKEWS]
            + [_point(s, "bursty", *bursty[s]) for s in SKEWS])
