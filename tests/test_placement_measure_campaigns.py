import pytest

from harness.scheduler import ScheduledRun
from harness.submit import SubmitOutcome
from placement_measure.campaigns import (
    CellDesign,
    SwapDesign,
    cell_condition,
    parse_cell,
    parse_swap,
    swap_condition,
)
from placement_measure.records import A4Run, build_record


def test_conditions_round_trip():
    assert parse_swap(swap_condition("Qwen/Qwen3-4B", "Qwen/Qwen3-4B-Base", True)) == (
        "Qwen/Qwen3-4B", "Qwen/Qwen3-4B-Base", True)
    assert parse_cell(cell_condition(8, 16)) == (8, 16)
    assert parse_cell(cell_condition(8, None)) == (8, None)
    with pytest.raises(ValueError):
        parse_cell("c8")


def test_a_swap_design_interleaves_every_pair_and_state_per_block():
    design = SwapDesign(pairs=(("Qwen/Qwen3-4B", "Qwen/Qwen3-4B-Base"),), cold_states=(True, False),
                        repeats=3, seed=1)
    sched = design.schedule()
    assert len(sched) == 6
    for b in range(3):
        assert len({s.condition for s in sched if s.block_index == b}) == 2
    payload = design.payload(sched[0], "rid")
    assert payload["kind"] == "swap" and payload["run_id"] == "rid"


def test_a_cell_design_sizes_the_neighbour_to_outlast_the_measured_run():
    design = CellDesign(measured_model="Qwen/Qwen3-4B", neighbour_model="Qwen/Qwen3-4B-Base",
                        own_levels=(2, 8), neighbour_levels=(0, 8), solo=True, input_len=1024,
                        output_len=256, repeats=2, seed=3)
    assert len(design.conditions()) == 6
    p = design.payload(ScheduledRun(0, 0, "pair:o2:n8"), "rid")
    cell = p["cell"]
    # 100 measured prompts at concurrency 2 is 51 waves; the neighbour gets
    # four times that many waves of 8.
    assert cell["num_prompts"] == 100 and cell["neighbour_prompts"] == 4 * 8 * 51
    solo = design.payload(ScheduledRun(1, 0, "solo:o8"), "rid")
    assert solo["b"] is None and solo["a"]["gpu_memory_utilization"] == 0.92


def _outcome(payload=None, error=None, diagnostics=None):
    return SubmitOutcome(clock_A={"t_submit": 0.0, "t_result": 1.0}, payload=payload, error=error,
                         diagnostics=diagnostics)


def test_records_are_ok_only_with_a_measurement():
    s = ScheduledRun(0, 0, "swap:a>b:cold")
    ok = build_record(s, "r", _outcome({"swap_s": 30.0}), kind="swap", source="stub")
    no_time = build_record(s, "r", _outcome({"swap_s": None, "failure": "x"}), kind="swap", source="stub")
    failed = build_record(s, "r", _outcome(error="boom", diagnostics={"b": {}}), kind="swap", source="stub")
    assert (ok.outcome, no_time.outcome, failed.outcome) == ("ok", "failed", "failed")
    assert failed.output == {"b": {}} and failed.failure == "boom"
    assert A4Run.from_dict(ok.to_dict()) == ok
