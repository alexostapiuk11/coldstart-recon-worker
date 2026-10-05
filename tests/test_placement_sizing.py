import pytest

from placement.evaluate import ConfigOutcome, GridPoint, PointEvaluation
from placement.sizing import size, sized_fleet


def _outcome(strategy, m, p99s_per_rep):
    """`p99s_per_rep` is one value per repetition, applied to every decile."""
    return ConfigOutcome(
        strategy=strategy,
        m=m,
        decile_p99s=tuple((v,) * 10 for v in p99s_per_rep),
        swaps=(0,) * len(p99s_per_rep),
        extrapolated=(0,) * len(p99s_per_rep),
    )


def test_the_smallest_m_whose_median_p99_meets_the_slo_wins():
    outcomes = [
        _outcome("swap", 3, [9.0, 9.0, 9.0]),
        _outcome("swap", 4, [1.0, 9.0, 2.0]),  # median 2.0 meets 5.0
        _outcome("swap", 5, [1.0, 1.0, 1.0]),
    ]
    assert size(outcomes, [0, 1, 2], slo=5.0) == 4


def test_a_strategy_that_never_meets_the_slo_is_dominated():
    assert size([_outcome("swap", 3, [9.0])], [0], slo=5.0) is None


def test_resampled_reps_with_duplicates_change_the_answer():
    outcomes = [_outcome("swap", 3, [1.0, 9.0, 9.0]), _outcome("swap", 4, [1.0, 1.0, 1.0])]
    assert size(outcomes, [0, 1, 2], slo=5.0) == 4
    assert size(outcomes, [0, 0, 1], slo=5.0) == 3


def test_every_decile_must_meet_it():
    worst = ConfigOutcome("swap", 3, ((1.0,) * 9 + (9.0,),), (0,), (0,))
    assert size([worst], [0], slo=5.0) is None


def test_configurations_out_of_order_are_refused():
    with pytest.raises(ValueError, match="ascending"):
        size([_outcome("swap", 5, [1.0]), _outcome("swap", 4, [1.0])], [0], slo=5.0)


def test_a_decile_under_the_floor_cannot_be_sized():
    thin = ConfigOutcome("swap", 3, ((1.0,) * 9 + (None,),), (0,), (0,))
    with pytest.raises(ValueError, match="floor"):
        size([thin], [0], slo=5.0)


def _evaluation(counts):
    outcomes = {
        "dedicate": (_outcome("dedicate", 6, [1.0]),),
        "swap": (_outcome("swap", 3, [9.0]), _outcome("swap", 4, [1.0])),
        "colocate": (_outcome("colocate", 5, [1.0]),),
    }
    return PointEvaluation(GridPoint(1.0, "spread", 100.0), outcomes, counts)


def test_a_grid_point_is_sized_only_when_every_decile_cleared_the_floor():
    assert sized_fleet(_evaluation(((500,) * 10,)), [0], slo=5.0) == {
        "dedicate": 6,
        "swap": 4,
        "colocate": 5,
    }
    assert sized_fleet(_evaluation(((500,) * 9 + (499,),)), [0], slo=5.0) is None
