from collections import Counter

import pytest

from multilora.conditions import (
    CONCENTRATED,
    GATE,
    REAL,
    SPREAD,
    SYNTHETIC,
    campaign_conditions,
    campaign_schedule,
    gate_schedule,
    parse_condition,
    phase_plan,
    registered_adapters,
    topup_schedule,
)
from tests.conftest import example_prereg


def test_campaign_conditions_cover_sweep_diagnostic_and_control(prereg):
    assert campaign_conditions(prereg) == [
        "sweep-N1", "sweep-N2", "sweep-N4", "sweep-N8", "sweep-N16", "sweep-N32", "sweep-N64",
        "diag-N1", "diag-N16", "diag-N64", "ctrl-N64",
    ]


def test_cut_conditions_disappear_from_the_schedule():
    cut = example_prereg(include_diagnostic=False, include_control=False)
    assert campaign_conditions(cut) == [f"sweep-N{n}" for n in cut.sweep]


def test_every_condition_gets_the_pre_registered_instance_count(prereg):
    counts = Counter(s.condition for s in campaign_schedule(prereg))
    assert set(counts.values()) == {prereg.instances_per_condition}
    assert len(counts) == 11


def test_the_gate_has_its_own_schedule(prereg):
    sched = gate_schedule(prereg)
    assert {s.condition for s in sched} == {GATE}
    assert len(sched) == prereg.instances_per_condition


def test_parse_condition_sets_the_per_job_switches(prereg):
    assert parse_condition("sweep-N16", prereg).n_slots == 16
    diag = parse_condition("diag-N64", prereg)
    assert diag.specialize_active_lora and not diag.disable_log_stats
    ctrl = parse_condition("ctrl-N64", prereg)
    assert ctrl.disable_log_stats and not ctrl.specialize_active_lora
    assert parse_condition(GATE, prereg).n_slots == 8


@pytest.mark.parametrize("bad", ["sweep-N3", "diag-N8", "ctrl-N32", "nonsense"])
def test_unregistered_conditions_are_refused(prereg, bad):
    with pytest.raises(ValueError):
        parse_condition(bad, prereg)


def test_sweep_phases_alternate_regimes_with_the_right_adapter_lists(prereg):
    phases = phase_plan(parse_condition("sweep-N16", prereg), prereg, run_index=3)
    assert Counter(p.regime for p in phases) == {CONCENTRATED: 2, SPREAD: 2}
    assert [p.phase_index for p in phases] == [0, 1, 2, 3]
    for p in phases:
        if p.regime == CONCENTRATED:
            assert p.adapters == ("a00",)
        else:
            assert p.adapters == registered_adapters(parse_condition("sweep-N16", prereg), prereg)
            assert len(p.adapters) == 16


def test_phase_order_is_reproducible_and_varies_between_instances(prereg):
    cond = parse_condition("sweep-N8", prereg)
    assert phase_plan(cond, prereg, 7) == phase_plan(cond, prereg, 7)
    orders = {tuple(p.regime for p in phase_plan(cond, prereg, i)) for i in range(20)}
    assert len(orders) > 1


def test_at_one_slot_the_two_regimes_list_the_same_adapter(prereg):
    phases = phase_plan(parse_condition("sweep-N1", prereg), prereg, 0)
    assert {p.adapters for p in phases} == {("a00",)}


def test_gate_phases_compare_real_and_synthetic_sets_of_equal_size(prereg):
    phases = phase_plan(parse_condition(GATE, prereg), prereg, 2)
    assert Counter(p.regime for p in phases) == {REAL: 2, SYNTHETIC: 2}
    real = next(p.adapters for p in phases if p.regime == REAL)
    synth = next(p.adapters for p in phases if p.regime == SYNTHETIC)
    assert real == ("r00", "r01", "r02", "r03")
    assert synth == ("s00", "s01", "s02", "s03")


def test_a_top_up_covers_only_the_named_conditions(prereg):
    sched = topup_schedule(prereg, ["sweep-N64", "diag-N16"], blocks=3)
    assert Counter(s.condition for s in sched) == {"sweep-N64": 3, "diag-N16": 3}


def test_a_top_up_refuses_the_gate_and_unregistered_names(prereg):
    with pytest.raises(ValueError, match="registered campaign conditions"):
        topup_schedule(prereg, ["gate"], blocks=1)
    with pytest.raises(ValueError, match="registered campaign conditions"):
        topup_schedule(prereg, ["sweep-N3"], blocks=1)
