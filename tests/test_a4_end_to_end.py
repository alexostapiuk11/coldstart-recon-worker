"""GPU-free proof that the pipeline answers the question it exists for.

Small, measured-flagged synthetic inputs, so every run is seconds, not minutes.
Two properties are checked through the real traffic, simulator, evaluation and
sizing code, because each would expose a wrong rule rather than a wrong number:

- When swaps cost nothing, swap needs fewer GPUs than dedicate.
- When swaps cost hours, the only swap configuration meeting the SLO is the one
  with a pool slot for every tail model, which is dedicate's M exactly.
"""

from autoscale.service import ServiceCurve
from placement.colocated import ColocatedSurface
from placement.evaluate import GridPoint, Scenario, evaluate_point
from placement.resample import EmpiricalDistribution
from placement.sim import Engines
from placement.sizing import sized_fleet

CURVE = ServiceCurve(points=[(1, 0.2, 5.0, 0.3), (4, 0.3, 13.3, 1.0)], measured=True)
SURFACE = ColocatedSurface(
    own=(1, 4), neighbour=(0, 4), latency=((0.21, 0.3), (0.32, 0.45)), measured=True
)
ENGINES = Engines(CURVE, SURFACE)
FREE = EmpiricalDistribution(samples=(0.0,), measured=True)
PROHIBITIVE = EmpiricalDistribution(samples=(10_000.0,), measured=True)
# Ten models at 4 rps each, uniform: 640 expected requests per decile in the
# 160 s window, comfortably over the 500 floor in every repetition.
SCENARIO = Scenario(
    n_models=10, offered_gpus=3.0, saturation_rps=40.0 / 3.0, hot_fraction=0.7,
    warmup=5.0, mean_burst=5.0, duty=0.3,
)
POINT = GridPoint(s=0.0, regime="spread", until=165.0)
SLO = 2.0


def _sized(swap_time):
    evaluation = evaluate_point(POINT, SCENARIO, ENGINES, swap_time, repetitions=3, seed=1)
    assert evaluation.floor_met
    return sized_fleet(evaluation, [0, 1, 2], SLO)


def test_free_swaps_need_fewer_gpus_than_dedicate():
    sized = _sized(FREE)
    assert sized["dedicate"] == 10
    assert sized["swap"] is not None and sized["swap"] < sized["dedicate"]


def test_prohibitive_swaps_size_swap_to_dedicates_m():
    sized = _sized(PROHIBITIVE)
    assert sized["swap"] == sized["dedicate"] == 10
