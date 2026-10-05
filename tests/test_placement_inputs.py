"""The reductions' refusals, on hand-built records. The happy path runs end to
end in tests/test_a4_measure_end_to_end.py."""

import pytest

from placement.inputs import cell_validity, colocated_surface, swap_distribution
from placement_measure.records import A4Run


def test_a_cell_whose_neighbour_ran_out_does_not_count():
    rec = A4Run(run_id="r", run_index=0, condition="pair:o4:n4", block_index=0, kind="cell",
                outcome="ok", failure=None, clock_A={}, source="stub",
                output={"run": {"latency_s": 1.0, "throughput_tps": 1.0, "gpu_util": 1.0},
                        "neighbour_load": {"level": 4, "ramp": {"reached": True},
                                           "ended_before_measured_run": True}})
    assert "ran out" in cell_validity(rec)
    with pytest.raises(ValueError, match="interpolate"):
        colocated_surface([rec], own_levels=(4,), neighbour_levels=(4,), min_repeats=1)


def test_the_swap_distribution_draws_only_the_requested_cache_state():
    def rec(cond, s):
        return A4Run(run_id="r", run_index=0, condition=cond, block_index=0, kind="swap",
                     outcome="ok", failure=None, clock_A={}, source="stub", output={"swap_s": s})

    records = [rec("swap:a>b:cold", 40.0), rec("swap:a>b:warm", 20.0), rec("swap:b>a:cold", 41.0)]
    assert swap_distribution(records, cold=True).samples == (40.0, 41.0)
    with pytest.raises(ValueError):
        swap_distribution(records, cold=False, targets={"zzz"})
