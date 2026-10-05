"""The stops in pre-registration step 2's rules that the main test file leaves out.

A rule whose input reconnaissance did not answer raises `NotDecidable`, never a
default. Each test here pins one such stop by its own message, so a guard that
went missing would be caught even if a different `NotDecidable` fired in its
place.
"""

import pytest
from a4_examples import example_report

from placement import step2
from placement.step2 import NotDecidable, measurement_design, provisional_swap_samples


def test_a_grid_too_small_to_hold_cells_out_of_stops():
    """A split KV ceiling of 2 or less gives `own` only 1, 2, 4: too few levels
    to put a held-out cell between grid points, and no value to fall back on."""
    with pytest.raises(NotDecidable, match="too small to hold cells out of"):
        step2.held_out_cells((1, 2, 4), (0, 1, 2, 4))
    # Reachable from a report: 1,100 tokens of split KV is a ceiling of 2 at 512.
    assert step2.power_levels(2) == (1, 2, 4)
    report = example_report()
    report["go_no_go"]["primary"]["kv_capacity_tokens"] = [1_100, 1_100]
    with pytest.raises(NotDecidable, match="too small to hold cells out of"):
        measurement_design(report)


def test_no_compile_cache_hit_swap_in_the_simulated_state_stops():
    """The screen draws swap times from reconnaissance's own swaps in the
    simulated state, compile-cache hits only; with none there is nothing to draw."""
    report = example_report()
    measurement = measurement_design(report)
    assert measurement["simulated_swap"]["cold"] is True
    for row in report["cache_eviction"]:
        if row["cold"]:
            row["b_compiled"] = True
    with pytest.raises(NotDecidable, match="no cold swap with a compile-cache hit"):
        provisional_swap_samples(report, measurement)

    # The warm state is the same stop: its rows come from both probes.
    report = example_report()
    report["cache_eviction"][1]["cached_kib_drop"] = 0
    measurement = measurement_design(report)
    assert measurement["simulated_swap"]["cold"] is False
    warm_rows = [r for r in report["cache_eviction"] if not r["cold"]] + report["compile_reuse"]
    for row in warm_rows:
        row["b_compiled"] = True
    with pytest.raises(NotDecidable, match="no warm swap with a compile-cache hit"):
        provisional_swap_samples(report, measurement)


def test_an_unanswered_fallback_go_no_go_stops_when_the_primary_failed():
    """The primary failed, so the fallback decides; its silence is not a fail."""
    report = example_report()
    report["go_no_go"]["primary"]["passed"] = False
    report["go_no_go"]["fallback"] = {"answered": False, "passed": None}
    with pytest.raises(NotDecidable, match="did not answer the fallback go/no-go"):
        step2.model_class(report)
    with pytest.raises(NotDecidable, match="did not answer the fallback go/no-go"):
        measurement_design(report)


def test_a_report_with_no_compile_reuse_rows_stops():
    """No swap-in was read at all: that is not 'every swap-in reused the cache'."""
    with pytest.raises(NotDecidable, match="compile state"):
        step2.compile_shared(example_report(compile_reuse=[]))
    with pytest.raises(NotDecidable, match="compile state"):
        measurement_design(example_report(compile_reuse=[]))
