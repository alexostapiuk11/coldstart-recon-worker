from collections import Counter

from coldstart.scheduler import build_schedule


def test_each_triple_contains_each_arm_exactly_once():
    sched = build_schedule(arms=["A", "B", "C"], triples=10, seed=1)
    assert len(sched) == 30
    for i in range(0, 30, 3):
        assert sorted(s.arm for s in sched[i : i + 3]) == ["A", "B", "C"]


def test_run_index_and_triple_index_are_sequential():
    sched = build_schedule(arms=["A", "B", "C"], triples=4, seed=1)
    assert [s.run_index for s in sched] == list(range(12))
    assert [s.triple_index for s in sched[:6]] == [0, 0, 0, 1, 1, 1]


def test_same_seed_is_reproducible_and_different_seed_is_not():
    a = [s.arm for s in build_schedule(["A", "B", "C"], 20, seed=7)]
    b = [s.arm for s in build_schedule(["A", "B", "C"], 20, seed=7)]
    c = [s.arm for s in build_schedule(["A", "B", "C"], 20, seed=8)]
    assert a == b
    assert a != c


def test_arms_are_balanced_overall():
    sched = build_schedule(["A", "B", "C"], 30, seed=3)
    assert Counter(s.arm for s in sched) == {"A": 30, "B": 30, "C": 30}


def test_arm_order_varies_between_triples():
    sched = build_schedule(["A", "B", "C"], 30, seed=5)
    first_of_each_triple = [sched[i].arm for i in range(0, 90, 3)]
    assert len(set(first_of_each_triple)) == 3, "every triple began with the same arm"
