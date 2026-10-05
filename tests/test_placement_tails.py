import pytest

from placement.sim import RunResult
from placement.tails import P99_FLOOR, decile_counts, decile_p99s

DECILES_OF_TEN = tuple(range(10))  # ten models, one per decile


def _result(latencies_by_model):
    result = RunResult(m=1)
    for model, latencies in latencies_by_model.items():
        for latency in latencies:
            result.arrivals.append(0.0)
            result.models.append(model)
            result.latencies.append(latency)
    return result


def test_the_floor_is_the_shared_statistics_floor():
    assert P99_FLOOR == 500


def test_a_decile_at_the_floor_reports_the_linear_interpolation_p99():
    # 1..500: p99 at index 0.99 * 499 = 494.01 lands between 495 and 496.
    result = _result({0: [float(v) for v in range(1, 501)]})
    p99s = decile_p99s(result, DECILES_OF_TEN)
    assert p99s[0] == pytest.approx(495.01)


def test_a_decile_under_the_floor_reports_none_not_a_number():
    result = _result({0: [1.0] * 500, 9: [1.0] * 499})
    p99s = decile_p99s(result, DECILES_OF_TEN)
    assert p99s[0] == 1.0
    assert p99s[9] is None
    assert p99s[1:9] == (None,) * 8


def test_counts_group_models_into_their_deciles():
    assert decile_counts([0, 1, 1, 19], tuple(k // 2 for k in range(20))) == (
        3, 0, 0, 0, 0, 0, 0, 0, 0, 1,
    )
