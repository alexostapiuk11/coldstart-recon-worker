import pytest

from placement.fleet import Gpu, Placement, family, hot_allocation
from placement.traffic import zipf_shares


def test_a_model_above_the_hot_fraction_gets_enough_pinned_gpus():
    # Model 0 carries 0.6 of 4 GPUs of load = 2.4 GPUs; at 0.7 per GPU that
    # needs ceil(2.4 / 0.7) = 4 pinned GPUs. Model 1 carries 0.8, also hot.
    hot = hot_allocation((0.6, 0.2, 0.1, 0.1), offered_gpus=4.0, hot_fraction=0.7)
    assert hot == {0: 4, 1: 2}


def test_nothing_is_hot_at_low_load():
    assert hot_allocation(zipf_shares(20, 1.0), offered_gpus=0.5, hot_fraction=0.7) == {}


def test_dedicate_is_one_gpu_per_tail_model_plus_pinned():
    (only,) = family("dedicate", (0.6, 0.2, 0.1, 0.1), {0: 4})
    assert only.m == 4 + 3
    assert only.served == {0, 1, 2, 3}


def test_swap_grows_its_pool_and_reaches_dedicates_m():
    shares = (0.6, 0.2, 0.1, 0.1)
    configs = family("swap", shares, {0: 4})
    assert [c.m for c in configs] == [5, 6, 7]
    assert configs[0].pool_models == (1, 2, 3)
    # The first residents are the most popular tail models.
    assert [g.models for g in configs[1].gpus if g.kind == "pool"] == [(1,), (2,)]
    assert configs[-1].m == family("dedicate", shares, {0: 4})[0].m


def test_colocate_pairs_hot_with_cold_and_unpairs_busiest_first():
    shares = zipf_shares(6, 1.0)
    configs = family("colocate", shares, {})
    assert [c.m for c in configs] == [3, 4, 5, 6]
    first = {g.models for g in configs[0].gpus}
    assert first == {(0, 5), (1, 4), (2, 3)}
    # The busiest pair, (0, 5), is the first to be split.
    assert (0, 5) not in {g.models for g in configs[1].gpus}
    assert all(g.kind == "solo" for g in configs[-1].gpus)


def test_an_odd_tail_leaves_one_model_solo():
    configs = family("colocate", zipf_shares(5, 1.0), {})
    assert configs[0].m == 3
    assert sum(g.kind == "solo" for g in configs[0].gpus) == 1


def test_every_strategy_serves_every_model():
    shares = zipf_shares(20, 1.5)
    hot = hot_allocation(shares, offered_gpus=4.0, hot_fraction=0.7)
    for strategy in ("dedicate", "swap", "colocate"):
        for placement in family(strategy, shares, hot):
            assert placement.served == set(range(20))


def test_all_hot_leaves_one_placement():
    assert len(family("swap", (0.5, 0.5), {0: 1, 1: 1})) == 1


@pytest.mark.parametrize(
    "gpus, pool_models",
    [
        ((Gpu("pool", (1,)),), ()),
        ((Gpu("pinned", (0,)),), (1,)),
        ((Gpu("pool", (1,)), Gpu("pool", (1,))), (1, 2)),
        ((Gpu("pinned", (0,)), Gpu("pool", (0,))), (0,)),
    ],
)
def test_an_inconsistent_swap_placement_is_refused(gpus, pool_models):
    with pytest.raises(ValueError):
        Placement("swap", gpus, pool_models)


def test_a_pair_needs_two_distinct_models():
    with pytest.raises(ValueError):
        Gpu("pair", (1, 1))
