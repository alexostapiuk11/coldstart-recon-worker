"""Figure 4's inputs: a swap's own stages from its logs, and artifact 1's
reference medians through the one adapter allowed to load `coldstart`."""

import subprocess
import sys
from pathlib import Path

import pytest

from placement.stages import STAGES, stage_medians, swap_stages
from placement_measure.records import A4Run

REPO = Path(__file__).resolve().parents[1]
LOADING = ("(EngineCore pid=1) INFO 10-12 10:00:05 [model_runner.py:329] Model loading took "
           "7.49 GiB and {w} seconds")
INIT = ("(EngineCore pid=1) INFO 10-12 10:00:15 [core.py:348] init engine (profile, create kv "
        "cache, warmup model) took {i} s (compilation: {c} s)")


def _swap(cold=True, *, weights=8.0, init=10.0, compile_s=0.3, startup=30.0, lines=None, i=0):
    log = lines if lines is not None else [LOADING.format(w=weights), INIT.format(i=init, c=compile_s)]
    return A4Run(run_id=f"s{i}", run_index=i, condition=f"swap:a>b:{'cold' if cold else 'warm'}",
                 block_index=0, kind="swap", outcome="ok", failure=None, clock_A={},
                 source="stub",
                 output={"teardown_s": 0.5, "release": {"seconds": 1.5}, "swap_s": 32.0,
                         "b": {"startup_s": startup, "log_tail": log,
                               "facts": {"s4b_s": compile_s}}})


def test_a_swap_splits_into_its_paid_stages():
    stages = swap_stages(_swap())
    assert stages == {"teardown_s": 0.5, "release_s": 1.5, "process_and_health_s": 12.0,
                      "weights_s": 8.0, "engine_init_rest_s": pytest.approx(9.7),
                      "compile_s": 0.3, "swap_s": 32.0}
    paid = sum(stages[k] for k in STAGES)
    assert paid == pytest.approx(stages["swap_s"])


def test_a_log_without_its_stage_lines_is_refused():
    with pytest.raises(ValueError, match="model-loading"):
        swap_stages(_swap(lines=[INIT.format(i=10.0, c=0.3)]))
    with pytest.raises(ValueError, match="engine-init"):
        swap_stages(_swap(lines=[LOADING.format(w=8.0)]))


def test_stages_that_exceed_the_bring_up_are_refused():
    with pytest.raises(ValueError, match="exceed"):
        swap_stages(_swap(weights=25.0, init=10.0, startup=30.0))


def test_medians_are_over_the_simulated_cache_and_compile_state():
    records = [_swap(True, weights=8.0, i=0), _swap(True, weights=10.0, i=1),
               _swap(False, weights=2.0, i=2), _swap(True, compile_s=19.0, init=25.0, startup=45.0, i=3)]
    m = stage_medians(records, cold=True)
    assert m["n"] == 2 and m["stages"]["weights_s"] == pytest.approx(9.0)
    assert m["unreadable"] == []
    assert stage_medians(records, cold=True, compiled=True)["n"] == 1
    with pytest.raises(ValueError, match="no readable ok swap"):
        stage_medians(records, cold=False, compiled=True)


def test_the_reference_is_artifact_ones_arm_c():
    from placement.a1_reference import stage_medians as a1

    ref = a1(REPO / "data" / "campaign.jsonl")
    assert ref["arm"] == "C" and ref["n"] == 100 and ref["model"] == "Qwen/Qwen3-8B"
    assert ref["stages"]["t_weights"] == pytest.approx(21.34, abs=0.01)


def test_only_the_adapter_loads_coldstart():
    probe = ("import importlib, sys; importlib.import_module({!r}); "
             "print(any(m.startswith('coldstart') for m in sys.modules))")
    results = {}
    for module in ("placement.a1_reference", "placement.stages"):
        out = subprocess.run([sys.executable, "-c", probe.format(module)], cwd=REPO,
                             capture_output=True, text=True, check=True)
        results[module] = out.stdout.strip()
    assert results == {"placement.a1_reference": "True", "placement.stages": "False"}


def test_an_unreadable_log_is_counted_not_fatal_unless_nothing_is_readable():
    records = [_swap(True, i=0), _swap(True, lines=[INIT.format(i=10.0, c=0.3)], i=1)]
    m = stage_medians(records, cold=True)
    assert m["n"] == 1 and m["unreadable"][0]["run_id"] == "s1"
    with pytest.raises(ValueError, match="1 unreadable"):
        stage_medians(records[1:], cold=True)


def test_a_swap_without_a_compile_reading_is_in_no_stratum():
    record = _swap(True)
    record.output["b"]["facts"] = {}
    with pytest.raises(ValueError, match="no readable"):
        stage_medians([record], cold=True)
