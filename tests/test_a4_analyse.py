"""The analysis script end to end on synthetic stores, with the sweep's
evaluations replaced by hand-built ones (the sweep itself is tested in
tests/test_a4_sweep.py): every reduction, the validation, the held-out check,
figure 4's stages and the reference, and the analysis, into one file."""

import importlib.util
from pathlib import Path

import pytest
from a4_evaluations import sweep
from a4_stores import SWAP_S, write_stores

REPO = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("a4_analyse", REPO / "scripts" / "a4_analyse.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def analysis(tmp_path_factory):
    root = tmp_path_factory.mktemp("a4")
    reg = write_stores(root)
    script = _script()
    seen = {}

    def evaluations_for(design, engines, swap_time, out, workers, refresh=False):
        seen.update(design=design, engines=engines, swap_time=swap_time)
        return sweep()

    script.a4_sweep.evaluations_for = evaluations_for
    result = script.analyse_all(reg, script.STORES, root=root,
                                a1_store=REPO / "data" / "campaign.jsonl",
                                sweep_out=root / "sweep", workers=1)
    return result, seen, reg


def test_the_sweep_runs_on_the_measured_inputs_and_the_registered_choice(analysis):
    _, seen, reg = analysis
    design, engines, swap_time = seen["design"], seen["engines"], seen["swap_time"]
    assert engines.measured and swap_time.measured and design.preregistered
    # Cold compile-cache hits only: SWAP_S + 0.5 i + 4 for i in 0..7.
    assert swap_time.samples == tuple(SWAP_S + 0.5 * i + 4.0 for i in range(8))
    assert design.slo_seconds == pytest.approx(reg["SLO_SWAP_MULTIPLE"] * (SWAP_S + 4.0 + 1.75))
    assert design.offered_gpus == reg["OFFERED_GPUS"]


def test_the_inputs_held_out_check_and_validation_are_recorded(analysis):
    result, _, reg = analysis
    inputs = result["inputs"]
    assert inputs["solo_curve"][0][:2] == [1, pytest.approx(1.1)]
    assert inputs["surface"]["own"] == list(reg["OWN_LEVELS"])
    assert inputs["swaps"]["simulated"]["n"] == 8
    assert set(inputs["swaps"]["strata"]) == {"cold_hit", "warm_hit"}
    assert inputs["sleep_mode"]["n"] == 8
    assert inputs["stages"]["n"] == 8 and inputs["a1_reference"]["arm"] == "C"
    assert [c["passed"] for c in result["held_out"]] == [True, True]
    assert result["validation"]["outcome"] == "passed", result["validation"]["latency"]
    assert result["validation"]["point"] == {"regime": "bursty", "s": 1.0, "models": 3, "gpus": 1}


def test_the_analysis_itself_is_in_the_same_file(analysis):
    result, _, _ = analysis
    assert set(result["regimes"]) == {"spread", "bursty"}
    assert result["reference"] == {"regime": "bursty", "s": 1.0}
    assert result["rate"]["gpu_hourly_rate"] == 0.69
