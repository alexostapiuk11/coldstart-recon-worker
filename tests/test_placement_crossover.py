import pytest

from placement.crossover import cheapest, crossings, estimate_crossover
from placement.evaluate import ConfigOutcome, GridPoint, PointEvaluation

REPS = 20
FLOOR_MET = ((500,) * 10,) * REPS


def _outcome(strategy, m, p99s_per_rep):
    return ConfigOutcome(
        strategy=strategy,
        m=m,
        decile_p99s=tuple((v,) * 10 for v in p99s_per_rep),
        swaps=(0,) * REPS,
        extrapolated=(0,) * REPS,
    )


def _point(s, swap_small_p99s, counts=FLOOR_MET):
    """Dedicate needs 10 GPUs. Swap needs 10, or 6 when its small pool meets
    the SLO of 5 s -- which `swap_small_p99s` decides, repetition by repetition."""
    outcomes = {
        "dedicate": (_outcome("dedicate", 10, [1.0] * REPS),),
        "swap": (_outcome("swap", 6, swap_small_p99s), _outcome("swap", 10, [1.0] * REPS)),
        "colocate": (_outcome("colocate", 10, [1.0] * REPS),),
    }
    return PointEvaluation(GridPoint(s, "spread", 100.0), outcomes, counts)


def test_cheapest_reports_ties_and_domination():
    assert cheapest({"dedicate": 10, "swap": 6, "colocate": None}) == {"swap"}
    assert cheapest({"dedicate": 10, "swap": 10}) == {"dedicate", "swap"}
    assert cheapest({"dedicate": None, "swap": None}) == frozenset()


def test_crossings_skip_points_that_cannot_be_located():
    a, b = frozenset({"dedicate"}), frozenset({"swap"})
    assert crossings([a, a, b]) == ((1, 2),)
    assert crossings([a, None, frozenset(), b]) == ((0, 3),)
    assert crossings([a, a]) == ()


def test_a_clean_crossover_is_located_in_every_draw():
    # Swap's small pool fails at s=0.5 and passes at s=1.5 and 2.0 in every
    # repetition, so every resample finds the same single crossing.
    points = [_point(0.5, [9.0] * REPS), _point(1.5, [1.0] * REPS), _point(2.0, [1.0] * REPS)]
    got = estimate_crossover(points, slo=5.0, iterations=200)
    assert got.point == ((0, 1),)
    assert got.chosen[0] == {"dedicate", "swap", "colocate"}
    assert got.chosen[1] == {"swap"}
    assert (got.one_crossing, got.no_crossing, got.many_crossings) == (200, 0, 0)
    assert got.interval == (0, 0)


def test_a_borderline_point_widens_the_interval_rather_than_hiding():
    # At s=1.0 swap's small pool passes in exactly half the repetitions, so its
    # median sits on the SLO boundary and resamples disagree about it.
    half = [1.0] * (REPS // 2) + [9.0] * (REPS // 2)
    points = [_point(0.5, [9.0] * REPS), _point(1.0, half), _point(2.0, [1.0] * REPS)]
    got = estimate_crossover(points, slo=5.0, iterations=400, seed=1)
    assert got.one_crossing == 400
    assert got.interval == (0, 1)


def test_a_point_under_the_floor_is_excluded_not_guessed():
    thin = ((500,) * 9 + (499,),) + FLOOR_MET[1:]
    points = [_point(0.5, [9.0] * REPS), _point(1.0, [1.0] * REPS, counts=thin), _point(2.0, [1.0] * REPS)]
    got = estimate_crossover(points, slo=5.0, iterations=50)
    assert got.chosen[1] is None
    assert got.point == ((0, 2),)


def test_too_few_repetitions_are_refused():
    short = PointEvaluation(GridPoint(1.0, "spread", 100.0), _point(1.0, [1.0] * REPS).outcomes, FLOOR_MET[:5])
    with pytest.raises(ValueError, match="bootstrap"):
        estimate_crossover([short], slo=5.0)


def test_mixed_regimes_are_refused():
    a = _point(0.5, [9.0] * REPS)
    b = PointEvaluation(GridPoint(1.0, "bursty", 100.0), a.outcomes, FLOOR_MET)
    with pytest.raises(ValueError, match="one regime"):
        estimate_crossover([a, b], slo=5.0)
