"""Pre-registration step 2's rules, applied to example reconnaissance reports.

Each rule is checked on the answer it turns on, both ways, and every
unanswered input is a stop rather than a default.
"""

import random

import pytest
from a4_examples import BASE, FALLBACK, INSTRUCT, PRIMARY, example_report

from autoscale.service import ServiceCurve
from autoscale.traffic import saturation_rps
from placement import step2
from placement.step2 import (
    NotDecidable,
    SweepChoice,
    measurement_design,
    provisional_swap_samples,
    request_shape,
    sweep_design,
    validation_design,
)
from placement.traffic import bursty_trace, zipf_shares


def test_the_request_shape_is_the_shortest_at_which_the_split_kv_binds():
    # 18,100 // 512 = 35 > 32; // 1024 = 17 <= 32.
    assert request_shape(18_100) == {"input_len": 768, "output_len": 256, "split_ceiling": 17}
    # At the go/no-go floor, 16,384 // 512 = 32: the shortest candidate already binds.
    assert request_shape(16_384)["input_len"] == 256
    # A larger cache needs a longer request, up to T_max.
    assert request_shape(60_000) == {"input_len": 1792, "output_len": 256, "split_ceiling": 29}
    assert request_shape(200_000)["input_len"] + 256 == 2048


def test_a_cache_too_large_to_bind_below_max_num_seqs_stops():
    with pytest.raises(NotDecidable, match="cannot bind"):
        request_shape(2048 * 256)


def test_grids_run_past_their_kv_ceiling():
    assert step2.power_levels(17) == (1, 2, 4, 8, 16, 32)
    assert step2.power_levels(86) == (1, 2, 4, 8, 16, 32, 64, 128, 256)
    assert step2.power_levels(None)[-1] == 256


def test_the_primary_class_measures_everything_reconnaissance_allowed():
    m = measurement_design(example_report())
    assert m["model"] == PRIMARY and m["shape"]["input_len"] == 768
    assert m["own_levels"] == (1, 2, 4, 8, 16, 32) and m["neighbour_levels"] == (0, 8, 16, 32)
    # The solo ceiling is the measured model's own warm reading: the compiling
    # 86,000 and the -Base 88,100 are not it. 88,300 // 1024 = 86.
    assert m["kv_solo_tokens"] == 88_300 and m["solo_ceiling"] == 86
    assert m["held_out"] == ("pair:o12:n24", "pair:o24:n12")
    assert m["validation_set"] == (PRIMARY, BASE, INSTRUCT)
    assert m["simulated_swap"] == {"cold": True, "compiled": False}
    cells = m["cells"]
    conditions = cells.conditions()
    assert "pair:o32:n32" in conditions and "solo:o256" in conditions
    assert set(m["held_out"]) <= set(conditions)
    assert cells.neighbour_model == BASE and cells.repeats == step2.CELL_REPEATS
    swaps = m["swaps"]
    assert len(swaps.pairs) == 6 and swaps.cold_states == (True, False) and swaps.repeats == 3
    assert m["sleep"] is not None and m["sleep_simulated"] is False


def test_a_failed_primary_falls_back_with_three_tenants_of_one_checkpoint():
    report = example_report()
    report["go_no_go"]["primary"]["passed"] = False
    m = measurement_design(report)
    assert m["model"] == FALLBACK and m["validation_set"] == (FALLBACK,) * 3
    assert m["swaps"].pairs == ((FALLBACK, FALLBACK),) and m["swaps"].repeats == 16
    # Reconnaissance has no solo 1.7B reading, so the solo grid spans everything.
    assert m["solo_ceiling"] is None and m["solo_levels"][-1] == 256
    assert m["cells"].neighbour_model == FALLBACK


def test_both_classes_failing_or_an_unanswered_go_no_go_stops():
    report = example_report()
    report["go_no_go"]["primary"]["passed"] = False
    report["go_no_go"]["fallback"]["passed"] = False
    with pytest.raises(NotDecidable, match="design changes"):
        measurement_design(report)
    report["go_no_go"]["primary"] = {"answered": False, "passed": None}
    with pytest.raises(NotDecidable, match="did not answer"):
        measurement_design(report)


def test_a_compile_miss_on_any_swap_in_makes_the_validation_set_one_checkpoint():
    report = example_report()
    report["compile_reuse"][1]["b_compiled"] = True
    m = measurement_design(report)
    assert m["compile_shared"] is False and m["validation_set"] == (PRIMARY,) * 3


def test_eviction_that_did_not_empty_the_cache_leaves_only_warm_swaps():
    report = example_report()
    report["cache_eviction"][1]["cached_kib_drop"] = 100_000
    m = measurement_design(report)
    assert m["eviction_works"] is False and m["swaps"].cold_states == (False,)
    assert m["simulated_swap"]["cold"] is False


def test_unanswered_compile_or_eviction_questions_stop():
    report = example_report()
    report["compile_reuse"][0]["b_compiled"] = None
    with pytest.raises(NotDecidable, match="compile state"):
        measurement_design(report)
    with pytest.raises(NotDecidable, match="cold swap"):
        measurement_design(example_report(cache_eviction=[]))


def test_sleep_mode_that_does_not_work_is_not_measured():
    m = measurement_design(example_report(sleep_mode={"answered": True, "works": False}))
    assert m["sleep"] is None


def test_the_provisional_swaps_are_reconnaissances_own_in_the_simulated_state():
    report = example_report()
    m = measurement_design(report)
    assert provisional_swap_samples(report, m) == (44.0, 45.5)
    report["cache_eviction"][1]["cached_kib_drop"] = 0
    warm = provisional_swap_samples(report, measurement_design(report))
    assert warm == (31.0, 30.5, 33.0, 31.5, 32.2, 30.8)


def test_the_sweep_design_sets_the_slo_from_the_swap_median():
    design = sweep_design(SweepChoice(offered_gpus=2.0, slo_swap_multiple=4.0), 40.0)
    assert design.slo_seconds == 160.0 and design.offered_gpus == 2.0
    assert design.skews == step2.SKEWS and design.preregistered
    assert design.n_models == 20 and design.duty == 0.2
    with pytest.raises(ValueError):
        sweep_design(SweepChoice(2.0, 4.0), 0.0)


def test_the_validation_trace_is_one_draw_from_a_registered_seed():
    """One draw, not its expectation: over 900 s a bursty model has only a few
    ON periods, so the realised load can sit well below the target. The real
    repeats and the simulator replay the same draw, so that is no bias."""
    m = measurement_design(example_report())
    curve = ServiceCurve(points=[(1, 4.0, 60.0, 0.3), (16, 6.0, 600.0, 0.9),
                                 (32, 9.0, 800.0, 1.0)], measured=True)
    seed = step2.VALIDATION_SEEDS[1]
    design = validation_design(m, curve, seed)
    assert design == validation_design(m, curve, seed) and design.tenants == m["validation_set"]
    assert design.max_in_flight == 32 and design.cold is True and design.seed == seed
    expected = bursty_trace(zipf_shares(3, step2.VALIDATION_S),
                            step2.VALIDATION_LOAD * saturation_rps(curve),
                            step2.VALIDATION_WINDOW_S, step2.VALIDATION_MEAN_BURST_S,
                            step2.VALIDATION_DUTY, random.Random(seed))
    assert list(design.trace) == expected
    with pytest.raises(ValueError, match="pre-registered"):
        validation_design(m, curve, 17)
