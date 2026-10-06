"""A neighbour level above one engine's capacity counts as reached when the
neighbour sat at capacity with the rest queued (docs/experiment-a4.md,
"Amendment, 2026-10-06 (validity)"); and a cell design can lengthen the
neighbour's ramp window ("Amendment, 2026-10-06 (ramp window)")."""

from dataclasses import fields

from placement import registered
from placement.inputs import cell_validity
from placement_measure.campaigns import CellDesign
from placement_measure.colocation import CellSpec
from placement_measure.prereg import FALLBACK
from placement_measure.records import A4Run

CAP = registered.SPLIT_CEILING


def _rec(level, *, reached=False, last=0, median=None, ended=False):
    load = {"level": level, "ramp": {"reached": reached, "last": {"running": last}},
            "median_running": median, "ended_before_measured_run": ended}
    return A4Run(run_id="r", run_index=0, condition=f"pair:o8:n{level}", block_index=0,
                 kind="cell", outcome="ok", failure=None, clock_A={}, source="stub",
                 output={"run": {"latency_s": 1.0, "throughput_tps": 1.0, "gpu_util": 1.0},
                         "neighbour_load": load})


def test_a_neighbour_above_capacity_that_sat_at_capacity_counts():
    assert cell_validity(_rec(CAP + 38, last=CAP + 1, median=CAP + 1)) is None


def test_a_neighbour_at_capacity_only_in_the_measured_run_does_not_count():
    # The ramp ended with nothing running: the measured run began before the
    # neighbour was loaded, so its early part was measured against no neighbour.
    assert "never reached" in cell_validity(_rec(CAP + 38, last=0, median=CAP + 1))


def test_a_neighbour_above_capacity_that_stayed_below_it_does_not_count():
    assert "never reached" in cell_validity(_rec(CAP + 38, last=CAP, median=CAP - 5))


def test_a_level_within_capacity_still_has_to_reach_its_level():
    assert "never reached" in cell_validity(_rec(16, last=16, median=16))
    assert cell_validity(_rec(16, reached=True, last=16, median=16)) is None


def test_a_saturated_neighbour_that_ran_out_still_does_not_count():
    assert "ran out" in cell_validity(_rec(CAP + 38, last=CAP + 1, median=CAP + 1, ended=True))


def _design(**kw):
    return CellDesign(measured_model=FALLBACK, neighbour_model=FALLBACK, own_levels=(1,),
                      neighbour_levels=(64,), solo=False, input_len=1792, output_len=256,
                      repeats=1, seed=1, **kw)


def _cell(design):
    return design.payload(design.schedule()[0], "r")["cell"]


def test_the_default_payload_does_not_carry_a_ramp_window():
    assert "ramp_timeout_s" not in _cell(_design())  # unchanged for every committed design


def test_a_design_can_set_the_ramp_window_and_the_worker_accepts_it():
    cell = _cell(_design(ramp_timeout_s=300.0))
    assert cell["ramp_timeout_s"] == 300.0
    assert CellSpec(**cell).ramp_timeout_s == 300.0
    assert "ramp_timeout_s" in {f.name for f in fields(CellSpec)}
