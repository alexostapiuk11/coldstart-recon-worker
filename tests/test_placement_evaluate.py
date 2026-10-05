from autoscale.service import ServiceCurve
from placement.colocated import ColocatedSurface
from placement.evaluate import (
    GridPoint,
    Scenario,
    dump_evaluations,
    evaluate_point,
    load_evaluations,
)
from placement.resample import EmpiricalDistribution
from placement.sim import Engines

CURVE = ServiceCurve(points=[(1, 0.2, 5.0, 0.3), (4, 0.3, 13.0, 1.0)], measured=True)
SURFACE = ColocatedSurface(
    own=(1, 4), neighbour=(0, 4), latency=((0.2, 0.3), (0.3, 0.45)), measured=True
)
ENGINES = Engines(CURVE, SURFACE)
SWAP = EmpiricalDistribution(samples=(2.0, 3.0), measured=True)
SCENARIO = Scenario(
    n_models=10, offered_gpus=1.5, saturation_rps=13.3, hot_fraction=0.7,
    warmup=5.0, mean_burst=5.0, duty=0.3,
)


def _evaluate(point, seed=0, reps=2):
    return evaluate_point(point, SCENARIO, ENGINES, SWAP, repetitions=reps, seed=seed)


def test_every_strategy_reports_every_configuration_in_ascending_m():
    evaluation = _evaluate(GridPoint(1.0, "spread", 40.0))
    for strategy, configs in evaluation.outcomes.items():
        ms = [c.m for c in configs]
        assert ms == sorted(ms), strategy
        assert all(len(c.decile_p99s) == 2 for c in configs)
    assert len(evaluation.outcomes["dedicate"]) == 1


def test_every_configuration_sees_the_same_traffic():
    """Common random numbers: the decile counts are a property of the trace,
    and the trace does not depend on the strategy or the configuration."""
    evaluation = _evaluate(GridPoint(0.0, "bursty", 40.0))
    assert evaluation.repetitions == 2
    assert evaluation.counts[0] != evaluation.counts[1]


def test_the_largest_swap_pool_never_swaps():
    evaluation = _evaluate(GridPoint(1.0, "spread", 40.0))
    assert set(evaluation.outcomes["swap"][-1].swaps) == {0}
    assert sum(evaluation.outcomes["swap"][0].swaps) > 0


def test_evaluation_is_reproducible_and_survives_the_cache(tmp_path):
    point = GridPoint(1.0, "spread", 40.0)
    first, again = _evaluate(point, seed=4), _evaluate(point, seed=4)
    assert first == again
    path = tmp_path / "cache.json"
    dump_evaluations(path, [first])
    assert load_evaluations(path) == [first]
