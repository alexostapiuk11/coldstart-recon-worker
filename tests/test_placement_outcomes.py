"""What each simulated configuration reports beyond the per-decile p99s that
sizing reads: the hit rate, the aggregate p99 and the per-decile SLO breach.

These are August §8's metrics. The aggregate p99 and the breach fraction carry
the post's fairness argument: a fleet sized on the aggregate looks fine while
its cold tenants miss the target (amendment §1e item 9).
"""

import json
import random

import pytest

from harness.stats import percentiles
from placement.evaluate import GridPoint, dump_evaluations, evaluate_point, load_evaluations
from placement.fleet import Gpu, Placement
from placement.resample import EmpiricalDistribution
from placement.sim import RunResult, simulate
from placement.tails import P99_FLOOR, aggregate_p99, decile_breach
from tests.test_placement_evaluate import ENGINES, SCENARIO, SWAP


def _swap_one_gpu():
    return Placement("swap", (Gpu("pool", (0,)),), pool_models=(0, 1))


def test_a_request_for_a_resident_model_is_a_hit_and_one_behind_a_swap_is_not():
    trace = [(1.0, 0), (2.0, 1), (2.5, 0), (40.0, 0)]
    result = simulate(trace, _swap_one_gpu(), ENGINES,
                      EmpiricalDistribution(samples=(10.0,), measured=True), 0.0, random.Random(0))
    # 0 is resident at t=1: a hit. 1 is not at t=2: a miss, and a swap to 1
    # (done at 12). 0 at 2.5 finds 1 loading: a miss, and a swap back (done at
    # 22.2, after 1's request drains). 0 at 40 is resident again: a hit.
    assert (result.hits, result.swaps) == (2, 2)
    assert len(result.latencies) == 4
    assert result.swap_starts == [2.0, pytest.approx(12.2)]


def test_warm_up_arrivals_are_not_counted_as_hits():
    trace = [(1.0, 0), (2.0, 0), (30.0, 0)]
    result = simulate(trace, _swap_one_gpu(), ENGINES, SWAP, 10.0, random.Random(0))
    assert result.hits == 1 and len(result.latencies) == 1


def test_the_aggregate_p99_is_over_every_request_and_refuses_a_thin_run():
    latencies = [float(i) for i in range(P99_FLOOR)]
    result = RunResult(m=1, arrivals=[0.0] * P99_FLOOR, models=[0] * P99_FLOOR, latencies=latencies)
    assert aggregate_p99(result) == percentiles(latencies, want=("p99",))["p99"]
    thin = RunResult(m=1, arrivals=[0.0], models=[0], latencies=[1.0])
    assert aggregate_p99(thin) is None


def test_the_breach_is_the_share_of_each_deciles_requests_above_the_slo():
    result = RunResult(m=1, arrivals=[0.0] * 5, models=[0, 0, 0, 9, 9],
                       latencies=[1.0, 3.0, 5.0, 1.0, 2.0])
    deciles = tuple(range(10))
    breach = decile_breach(result, deciles, slo=2.0)
    assert breach[0] == pytest.approx(2 / 3)
    assert breach[9] == 0.0  # 2.0 is not above an SLO of 2.0
    assert breach[1:9] == (None,) * 8


def test_the_evaluation_reports_every_metric_per_repetition():
    evaluation = evaluate_point(GridPoint(1.0, "spread", 40.0), SCENARIO, ENGINES, SWAP,
                                repetitions=2, seed=0, slo=1.0)
    for configs in evaluation.outcomes.values():
        for c in configs:
            assert len(c.aggregate_p99s) == len(c.hits) == len(c.requests) == 2
            assert len(c.decile_breach) == 2 and all(len(r) == 10 for r in c.decile_breach)
            assert all(h <= n for h, n in zip(c.hits, c.requests, strict=True))
            assert all(w <= s for w, s in zip(c.window_swaps, c.swaps, strict=True))
    dedicate = evaluation.outcomes["dedicate"][0]
    assert dedicate.hits == dedicate.requests  # every model always resident
    assert evaluation.outcomes["swap"][0].hits < evaluation.outcomes["swap"][0].requests


def test_without_an_slo_there_is_no_breach_and_sizing_is_unchanged():
    point = GridPoint(1.0, "spread", 40.0)
    plain = evaluate_point(point, SCENARIO, ENGINES, SWAP, repetitions=1, seed=3)
    with_slo = evaluate_point(point, SCENARIO, ENGINES, SWAP, repetitions=1, seed=3, slo=1.0)
    assert all(c.decile_breach == () for cs in plain.outcomes.values() for c in cs)
    for strategy in plain.outcomes:
        assert [c.decile_p99s for c in plain.outcomes[strategy]] == [
            c.decile_p99s for c in with_slo.outcomes[strategy]]


def test_the_new_fields_survive_the_cache_and_an_older_cache_still_loads(tmp_path):
    evaluation = evaluate_point(GridPoint(1.0, "spread", 40.0), SCENARIO, ENGINES, SWAP,
                                repetitions=1, seed=0, slo=1.0)
    path = tmp_path / "cache.json"
    dump_evaluations(path, [evaluation])
    assert load_evaluations(path) == [evaluation]
    raw = json.loads(path.read_text())
    for configs in raw[0]["outcomes"].values():
        for o in configs:
            for key in ("aggregate_p99s", "hits", "requests", "decile_breach", "window_swaps"):
                del o[key]
    path.write_text(json.dumps(raw))
    (old,) = load_evaluations(path)
    assert old.outcomes["swap"][0].hits == ()
