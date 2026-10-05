"""The post's headline numbers, rendered from a complete synthetic analysis."""

import pytest
from a4_analysis_example import example_analysis

from placement.post_numbers import numbers


@pytest.fixture(scope="module")
def nums(tmp_path_factory):
    return numbers(example_analysis(tmp_path_factory.mktemp("a4")))


def test_the_decision_rule_and_crossover_are_stated_per_regime(nums):
    assert nums["bursty_decision_rule"].startswith("s = 0.6: ")
    assert "swap" in nums["bursty_decision_rule"]
    assert nums["spread_crossover"].startswith("between s = ")


def test_the_reference_costs_are_dollars_with_cents(nums):
    for key in ("ref_dedicate_per_tenant", "ref_swap_per_tenant", "ref_dedicate_over_cheapest"):
        assert nums[key].startswith("$") and nums[key][-3] == "."


def test_the_fairness_number_is_a_whole_percentage(nums):
    assert nums["ref_swap_aggregate_coldest_breach"] == "25%"
    assert nums["ref_swap_aggregate_gpus"] == "5 GPUs"


def test_validation_and_inputs_are_stated(nums):
    assert nums["validation_outcome"] == "passed"
    assert nums["validation_bins"].endswith("judged bins")
    assert nums["held_out"] == "2 of 2 held-out cells"
    assert nums["swap_median"].endswith(" s") and nums["sleep_switch_median"].endswith(" s")
    assert nums["kv_split_ceiling"] == "17 requests" and nums["kv_solo_ceiling"] == "86 requests"
