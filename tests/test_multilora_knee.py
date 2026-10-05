import pytest

from multilora.knee import knee


def _flat(value: float, n: int = 24) -> list[float]:
    return [value * (1 + 0.001 * ((i % 5) - 2)) for i in range(n)]


def test_a_flat_curve_has_no_knee_and_reports_the_top():
    res = knee({1: _flat(100), 2: _flat(99), 4: _flat(98)}, tau=0.10, iterations=200)
    assert res["knee"] is None and res["above_top"]
    assert res["slots_below_knee"] == 4


def test_the_first_doubling_whose_drop_exceeds_tau_is_the_knee():
    curve = {1: _flat(100), 2: _flat(99), 4: _flat(97), 8: _flat(80), 16: _flat(60)}
    res = knee(curve, tau=0.10, iterations=200)
    assert res["knee"] == {"lower": 4, "upper": 8}
    assert res["slots_below_knee"] == 4
    eight = next(d for d in res["doublings"] if d["n"] == 8)
    assert eight["point"] == pytest.approx(1 - 80 / 97, rel=1e-3)
    assert eight["crosses"] and eight["resolved"]


def test_a_noisy_crossing_still_sets_the_knee_but_is_marked_unresolved():
    noisy = [110.0 if i % 2 else 70.0 for i in range(24)]
    res = knee({1: _flat(100), 2: noisy}, tau=0.05, iterations=500)
    d = res["doublings"][0]
    assert d["crosses"] and not d["resolved"]
    assert res["knee"] == {"lower": 1, "upper": 2}


def test_a_sweep_without_doublings_is_refused():
    with pytest.raises(ValueError, match="doublings"):
        knee({1: _flat(1), 3: _flat(1)}, tau=0.1, iterations=200)
