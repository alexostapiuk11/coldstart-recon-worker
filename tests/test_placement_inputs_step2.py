"""The reductions under pre-registration step 2's rules: warm-compile validity,
compile-filtered swaps, the sleep arm, held-out cells, top-ups and
multi-store reads."""

import pytest

from harness.store import JsonlStore
from placement.colocated import ColocatedSurface
from placement.inputs import (
    cell_summary,
    cell_validity,
    colocated_surface,
    held_out_check,
    load_records,
    short_cells,
    sleep_distribution,
    solo_curve,
    swap_distribution,
)
from placement_measure.records import A4Run


def _cell(condition, latency, s4b=0.3, kv=18_000, i=0, outcome="ok"):
    return A4Run(run_id=f"{condition}-{i}", run_index=i, condition=condition, block_index=0,
                 kind="cell", outcome=outcome, failure=None if outcome == "ok" else "x",
                 clock_A={}, source="stub",
                 output={"run": {"latency_s": latency, "throughput_tps": 10.0 * latency,
                                 "gpu_util": 0.9},
                         "engines": {"measured": {"facts": {"s4b_s": s4b,
                                                            "kv_capacity_tokens": kv}}},
                         "neighbour_load": {"level": 0}})


def _swap(condition, swap_s, s4b):
    return A4Run(run_id=condition, run_index=0, condition=condition, block_index=0, kind="swap",
                 outcome="ok", failure=None, clock_A={}, source="stub",
                 output={"swap_s": swap_s, "b": {"facts": {"s4b_s": s4b}}})


def test_a_compiling_measured_engine_is_excluded_only_under_the_rule():
    compiled = _cell("pair:o4:n0", 1.0, s4b=19.0)
    assert cell_validity(compiled) is None
    assert "compiled" in cell_validity(compiled, require_warm_compile=True)
    unread = _cell("pair:o4:n0", 1.0, s4b=None)
    assert "not read" in cell_validity(unread, require_warm_compile=True)


def test_the_rule_reaches_the_curve_and_the_surface():
    records = [_cell("solo:o1", 1.0, i=0), _cell("solo:o1", 1.2, i=1),
               _cell("solo:o1", 5.0, s4b=19.0, i=2),
               _cell("solo:o2", 1.5, i=0), _cell("solo:o2", 1.7, i=1)]
    curve = solo_curve(records, levels=(1, 2), min_repeats=2, require_warm_compile=True)
    assert curve.latency_at(1) == pytest.approx(1.1)
    with pytest.raises(ValueError, match="fewer than 3"):
        solo_curve(records, levels=(1, 2), min_repeats=3, require_warm_compile=True)


def test_a_held_out_cell_never_enters_the_surface_and_need_not_be_complete():
    grid = [_cell(f"pair:o{o}:n{n}", 1.0 + o + n, i=i)
            for o in (2, 4) for n in (0, 4) for i in range(2)]
    held = [_cell("pair:o3:n2", 99.0)]  # one repeat, wildly off: must not matter
    surface = colocated_surface(grid + held, own_levels=(2, 4), neighbour_levels=(0, 4),
                                min_repeats=2, require_warm_compile=True)
    assert surface.latency_at(3, 2) == pytest.approx(1.0 + 3 + 2)


def test_the_held_out_check_passes_inside_the_range_or_near_the_median():
    surface = ColocatedSurface(own=(2, 4), neighbour=(0, 4), latency=((1.0, 2.0), (3.0, 4.0)),
                               measured=True)
    # Predicted at (3, 2) is 2.5.
    near = [_cell("pair:o3:n2", v, i=i) for i, v in enumerate((2.6, 2.7, 2.8))]
    far = [_cell("pair:o3:n2", v, i=i) for i, v in enumerate((3.4, 3.5, 3.6))]
    inside = [_cell("pair:o3:n2", v, i=i) for i, v in enumerate((2.0, 2.9, 3.6))]

    def check(recs):
        return held_out_check(recs, surface, ["pair:o3:n2"], tolerance=0.1, min_repeats=3,
                              require_warm_compile=True)[0]

    assert check(near)["passed"] and check(inside)["passed"]
    result = check(far)
    assert not result["passed"] and result["predicted"] == pytest.approx(2.5)
    with pytest.raises(ValueError, match="valid repeats"):
        check(near[:2])


def test_the_summary_records_exclusions_and_kv():
    records = [_cell("pair:o4:n0", 1.0, kv=18_000, i=0), _cell("pair:o4:n0", 1.4, kv=18_200, i=1),
               _cell("pair:o4:n0", 9.0, s4b=19.0, i=2), _cell("pair:o4:n0", 0.0, i=3, outcome="failed")]
    s = cell_summary(records, require_warm_compile=True)["pair:o4:n0"]
    assert (s["n"], s["median"], s["lo"], s["hi"]) == (2, pytest.approx(1.2), 1.0, 1.4)
    assert s["kv_capacity_tokens"] == 18_100
    assert [e["reason"].split(",")[0] for e in s["excluded"]] == [
        "the measured engine compiled", "run failed: x"]


def test_short_cells_name_what_a_top_up_must_rerun():
    records = [_cell("pair:o4:n0", 1.0, i=i) for i in range(3)] + [
        _cell("pair:o4:n4", 1.0, i=0), _cell("pair:o4:n4", 1.0, s4b=19.0, i=1)]
    conditions = ["pair:o4:n0", "pair:o4:n4", "pair:o8:n0"]
    assert short_cells(records, conditions, min_repeats=3,
                       require_warm_compile=True) == ["pair:o4:n4", "pair:o8:n0"]


def test_swaps_are_drawn_by_compile_state_when_asked():
    records = [_swap("swap:a>b:cold", 40.0, 0.3), _swap("swap:b>a:cold", 70.0, 19.0),
               _swap("swap:a>b:warm", 30.0, 0.3)]
    assert swap_distribution(records, cold=True).samples == (40.0, 70.0)
    assert swap_distribution(records, cold=True, compiled=False).samples == (40.0,)
    assert swap_distribution(records, cold=True, compiled=True).samples == (70.0,)
    with pytest.raises(ValueError):
        swap_distribution(records, cold=False, compiled=True)


def test_the_sleep_arm_is_its_ok_switches():
    def rec(s, outcome="ok"):
        return A4Run(run_id="r", run_index=0, condition="sleep:a>b", block_index=0, kind="sleep",
                     outcome=outcome, failure=None, clock_A={}, source="stub",
                     output={"switch_s": s})

    assert sleep_distribution([rec(5.0), rec(None, "failed"), rec(6.0)]).samples == (5.0, 6.0)
    with pytest.raises(ValueError):
        sleep_distribution([rec(None, "failed")])


def test_records_load_from_several_stores_in_order(tmp_path):
    a, b = JsonlStore(tmp_path / "a.jsonl", A4Run), JsonlStore(tmp_path / "b.jsonl", A4Run)
    a.append(_cell("solo:o1", 1.0, i=0))
    b.append(_cell("solo:o1", 2.0, i=1))
    loaded = load_records([tmp_path / "a.jsonl", tmp_path / "b.jsonl"])
    assert [r.output["run"]["latency_s"] for r in loaded] == [1.0, 2.0]
