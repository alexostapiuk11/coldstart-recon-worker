"""The ranking-blind screen: its score, its tie-break, and the script's plumbing.

The score is checked on hand-built evaluations whose sized fleets are known,
so no simulation runs here. The script is checked with its evaluator patched,
which is what makes it fast: the screen's simulations are its own task step.
"""

import importlib.util
import json
from pathlib import Path

import pytest
from a4_examples import example_report

from placement import step2
from placement.evaluate import ConfigOutcome, GridPoint, PointEvaluation
from placement.screen import choose, run_screen, score, told_apart

REPO = Path(__file__).resolve().parents[1]


def _evaluation(s, p99_by_strategy, reps=2):
    """One grid point whose configurations have the given p99 in every
    decile and repetition: {strategy: [(m, p99), ...]}."""
    outcomes = {
        strategy: tuple(
            ConfigOutcome(strategy=strategy, m=m, decile_p99s=((p99,) * 10,) * reps,
                          swaps=(0,) * reps, extrapolated=(0,) * reps)
            for m, p99 in configs)
        for strategy, configs in p99_by_strategy.items()
    }
    return PointEvaluation(point=GridPoint(s, "spread", 100.0), outcomes=outcomes,
                           counts=((600,) * 10,) * reps)


SEPARATING = _evaluation(1.0, {"dedicate": [(10, 1.0)], "swap": [(6, 9.0), (8, 1.0)],
                               "colocate": [(5, 1.0)]})
TIED = _evaluation(1.5, {"dedicate": [(10, 1.0)], "swap": [(6, 9.0), (10, 1.0)],
                         "colocate": [(5, 9.0), (10, 1.0)]})


def test_a_point_scores_the_strategies_it_tells_apart():
    assert told_apart({"dedicate": 10, "swap": 8, "colocate": 5}) == 2
    # Co-locate alone differing tells only one strategy apart: the case that
    # made the first version of this score useless.
    assert told_apart({"dedicate": 10, "swap": 10, "colocate": 5}) == 1
    assert told_apart({"dedicate": 10, "swap": 10, "colocate": 10}) == 0
    assert told_apart({"dedicate": None, "swap": None, "colocate": None}) == 0
    assert told_apart(None) == 0


def test_the_score_sums_over_points_and_depends_on_the_slo():
    loose = score([SEPARATING, TIED], slo=2.0)
    assert (loose["score"], loose["evaluable"]) == (2, 2)
    # At an SLO under every p99 all three are dominated everywhere: degenerate.
    assert score([SEPARATING, TIED], slo=0.5)["score"] == 0


def test_a_tie_goes_to_the_earlier_candidate():
    scored = [{"score": 3, "n": 0}, {"score": 5, "n": 1}, {"score": 5, "n": 2}]
    assert choose(scored)["n"] == 1
    with pytest.raises(ValueError):
        choose([])


def test_the_screen_evaluates_once_per_load_and_scores_every_slo():
    calls = []

    def evaluate(offered):
        calls.append(offered)
        return [SEPARATING] if offered == 2.0 else [TIED]

    result = run_screen(evaluate, swap_median_s=1.0)
    assert calls == list(step2.SCREEN_OFFERED_GPUS)
    assert len(result["candidates"]) == len(step2.SCREEN_OFFERED_GPUS) * len(
        step2.SCREEN_SLO_SWAP_MULTIPLES)
    # Only offered 2.0 tells strategies apart, and at every SLO multiple (a
    # p99 equal to the SLO meets it). The tie goes to the tightest, 1.
    assert result["chosen"] == {"offered_gpus": 2.0, "slo_swap_multiple": 1.0}
    assert result["choice"] == step2.SweepChoice(2.0, 1.0)


def _script():
    spec = importlib.util.spec_from_file_location("a4_screen", REPO / "scripts" / "a4_screen.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_script_builds_the_registered_grid_on_provisional_inputs(tmp_path, monkeypatch):
    script = _script()
    seen = []

    def fake_evaluate_grid(points, scenario, engines, swap_time, repetitions, seed, slo, workers):
        seen.append({"points": points, "offered": scenario.offered_gpus, "swap": swap_time,
                     "repetitions": repetitions, "seed": seed, "slo": slo})
        return [SEPARATING]

    monkeypatch.setattr(script, "evaluate_grid", fake_evaluate_grid)
    monkeypatch.setattr(script, "grid", lambda design, scenario: [design])
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(example_report()))
    out = tmp_path / "screen.json"
    result = script.main(["--report", str(report_path), "--out", str(out), "--workers", "1"])
    assert [s["offered"] for s in seen] == list(step2.SCREEN_OFFERED_GPUS)
    first = seen[0]
    assert first["repetitions"] == step2.SCREEN_REPETITIONS and first["seed"] == step2.SCREEN_SEED
    assert first["slo"] is None and first["swap"].measured is False
    assert first["swap"].samples == (44.0, 45.5)
    design = first["points"][0]
    assert design.skews == step2.SKEWS and design.preregistered is False
    saved = json.loads(out.read_text())
    assert saved["chosen"] == result["chosen"] and saved["swap_median_s"] == pytest.approx(44.75)
    assert "PLACEHOLDER" in saved["provisional_inputs"]["engines"]
