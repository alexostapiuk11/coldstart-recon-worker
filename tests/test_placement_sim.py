"""The placement loop, against hand-computed scenarios.

FLAT serves any load up to 2 in exactly 1 s, so every latency below is a sum of
whole seconds a reader can check by hand. PAIR slows a co-located request by
0.5 s per request its neighbour has in flight. SWAP10 takes 10 s, every time.
"""

import random

import pytest

from autoscale.service import ServiceCurve
from placement.colocated import ColocatedSurface
from placement.fleet import Gpu, Placement, family
from placement.resample import EmpiricalDistribution
from placement.sim import Engines, simulate
from placement.traffic import spread_trace, zipf_shares

FLAT = ServiceCurve(points=[(1, 1.0, 1.0, 0.5), (2, 1.0, 2.0, 1.0)], measured=True)
PAIR = ColocatedSurface(own=(1, 2), neighbour=(0, 2), latency=((1.0, 2.0), (1.0, 2.0)), measured=True)
ENGINES = Engines(solo=FLAT, colocated=PAIR)
SWAP10 = EmpiricalDistribution(samples=(10.0,), measured=True)


def _run(trace, placement, warmup=0.0, swap=SWAP10, seed=0):
    return simulate(trace, placement, ENGINES, swap, warmup, random.Random(seed))


def _by_arrival(result):
    return sorted(zip(result.arrivals, result.models, result.latencies))


def _swap_pool(size, pool_models):
    gpus = tuple(Gpu("pool", (m,)) for m in pool_models[:size])
    return Placement("swap", gpus, pool_models=pool_models)


def test_a_dedicated_request_takes_its_measured_latency():
    placement = Placement("dedicate", (Gpu("solo", (0,)), Gpu("solo", (1,))))
    result = _run([(0.0, 0), (0.0, 1)], placement)
    assert result.latencies == [1.0, 1.0]


def test_a_request_beyond_capacity_waits_its_turn():
    placement = Placement("dedicate", (Gpu("solo", (0,)),))
    result = _run([(0.0, 0), (0.0, 0), (0.0, 0)], placement)
    assert sorted(result.latencies) == [1.0, 1.0, 2.0]


def test_a_hot_model_spreads_across_its_pinned_gpus():
    placement = Placement("dedicate", (Gpu("pinned", (0,)), Gpu("pinned", (0,))))
    four = _run([(0.0, 0)] * 4, placement)
    assert four.latencies == [1.0] * 4
    five = _run([(0.0, 0)] * 5, placement)
    assert sorted(five.latencies) == [1.0, 1.0, 1.0, 1.0, 2.0]


def test_a_colocated_request_is_slowed_by_its_neighbour():
    placement = Placement("colocate", (Gpu("pair", (0, 1)),))
    result = _run([(0.0, 0), (0.0, 1)], placement)
    # Model 0 dispatches first with an idle neighbour; model 1 then sees one
    # request in flight next door.
    assert _by_arrival(result) == [(0.0, 0, 1.0), (0.0, 1, 1.5)]


def test_a_non_resident_model_waits_for_a_swap():
    result = _run([(0.0, 1)], _swap_pool(1, (0, 1)))
    assert result.latencies == [11.0]
    assert result.swaps == 1


def test_the_victim_drains_before_it_swaps():
    # Model 0's request holds the GPU until t=1; the swap then runs 1..11.
    result = _run([(0.0, 0), (0.5, 1)], _swap_pool(1, (0, 1)))
    assert _by_arrival(result) == [(0.0, 0, 1.0), (0.5, 1, 11.5)]


def test_an_evicted_model_waits_for_a_swap_back():
    # t=0.5 model 1 evicts model 0: drain to 1, swap to 11, serve 11..12.
    # t=2 model 0 waits: the only GPU is busy swapping. At 11 it is scheduled,
    # the GPU drains model 1 at 12, swaps back by 22, and serves by 23.
    result = _run([(0.0, 0), (0.5, 1), (2.0, 0)], _swap_pool(1, (0, 1)))
    assert _by_arrival(result) == [(0.0, 0, 1.0), (0.5, 1, 11.5), (2.0, 0, 21.0)]
    assert result.swaps == 2


def test_a_model_already_being_swapped_in_gets_no_second_swap():
    result = _run([(0.0, 1), (1.0, 1)], _swap_pool(1, (0, 1)))
    assert result.swaps == 1
    # Both are dispatched when the swap finishes at t=10.
    assert _by_arrival(result) == [(0.0, 1, 11.0), (1.0, 1, 10.0)]


def test_lru_evicts_the_least_recently_used_resident():
    # Model 1 was last used at t=0, model 0 at t=3, so model 2 evicts model 1.
    trace = [(0.0, 1), (3.0, 0), (4.0, 2), (5.0, 0)]
    result = _run(trace, _swap_pool(2, (0, 1, 2)))
    assert result.swaps == 1
    assert _by_arrival(result)[-1] == (5.0, 0, 1.0)


def test_warmup_requests_run_but_are_not_reported():
    placement = Placement("dedicate", (Gpu("solo", (0,)),))
    result = _run([(0.0, 0), (0.0, 0), (0.0, 0), (5.0, 0)], placement, warmup=1.0)
    assert result.completed == 4
    assert _by_arrival(result) == [(5.0, 0, 1.0)]


def test_every_request_completes_even_under_heavy_swapping():
    shares = zipf_shares(10, 0.5)
    trace = spread_trace(shares, 6.0, 300.0, random.Random(4))
    placement = family("swap", shares, {})[1]
    result = _run(trace, placement)
    assert result.completed == len(trace) == len(result.latencies)
    assert result.swaps > 10


def test_the_same_seed_gives_the_same_run():
    shares = zipf_shares(10, 1.0)
    trace = spread_trace(shares, 4.0, 200.0, random.Random(1))
    placement = family("swap", shares, {})[2]
    varied = EmpiricalDistribution(samples=(5.0, 9.0, 14.0), measured=True)
    a = _run(trace, placement, swap=varied, seed=3)
    b = _run(trace, placement, swap=varied, seed=3)
    assert (a.latencies, a.swaps) == (b.latencies, b.swaps)


def test_a_model_the_placement_does_not_serve_is_refused():
    with pytest.raises(ValueError, match="does not serve"):
        _run([(0.0, 7)], Placement("dedicate", (Gpu("solo", (0,)),)))


def test_an_unsorted_trace_is_refused():
    with pytest.raises(ValueError, match="sorted"):
        _run([(2.0, 0), (1.0, 0)], Placement("dedicate", (Gpu("solo", (0,)),)))
