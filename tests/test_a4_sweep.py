"""The sweep script, end to end on small measured-flagged inputs.

It must refuse an unregistered design or unmeasured inputs unless told
otherwise, run the whole pipeline when told, and reuse its cache rather than
re-running a sweep whose inputs have not changed.
"""

import importlib.util
from pathlib import Path

import pytest

from autoscale.service import ServiceCurve
from placement.colocated import ColocatedSurface
from placement.design import Design
from placement.money import Assumptions
from placement.resample import EmpiricalDistribution
from placement.sim import Engines

REPO = Path(__file__).resolve().parents[1]
CURVE = ServiceCurve(points=[(1, 0.2, 5.0, 0.3), (4, 0.3, 13.3, 1.0)], measured=True)
SURFACE = ColocatedSurface(
    own=(1, 4), neighbour=(0, 4), latency=((0.21, 0.3), (0.32, 0.45)), measured=True
)
ENGINES = Engines(CURVE, SURFACE)
FREE = EmpiricalDistribution(samples=(0.0,), measured=True)
SLO = 2.0

def _script():
    spec = importlib.util.spec_from_file_location("a4_sweep", REPO / "scripts" / "a4_sweep.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DESIGN = Design(
    n_models=10, offered_gpus=3.0, hot_fraction=0.7, warmup=5.0, mean_burst=5.0,
    duty=0.3, skews=(0.0, 0.5), regimes=("spread",), repetitions=20, slo_seconds=SLO,
    pilot_traces=400, seed=5, preregistered=False,
)
RATE = Assumptions(gpu_hourly_rate=1.0, provenance="test")


def test_the_sweep_refuses_an_unregistered_design_without_the_flag(tmp_path):
    with pytest.raises(SystemExit, match="design"):
        _script().run(DESIGN, ENGINES, FREE, RATE, tmp_path, workers=1, allow_unmeasured=False)


def test_the_sweep_runs_end_to_end_and_reuses_its_cache(tmp_path, monkeypatch):
    script = _script()
    summary = script.run(DESIGN, ENGINES, FREE, RATE, tmp_path, workers=2, allow_unmeasured=True)
    rows = summary["regimes"]["spread"]["rows"]
    assert [row["s"] for row in rows] == [0.0, 0.5]
    assert all(row["sized"] is not None for row in rows)
    crossover = summary["regimes"]["spread"]["crossover"]
    assert crossover["no_crossing"] + crossover["one_crossing"] + crossover["many_crossings"] == 2000
    assert (tmp_path / "summary.json").is_file()

    def _must_not_run(*args, **kwargs):
        raise AssertionError("the cache should have been reused")

    # The sweep evaluates through `placement.grid.evaluate_grid` since plan 3
    # moved it there; patching the name the script calls is what proves the
    # cache was reused.
    monkeypatch.setattr(script, "evaluate_grid", _must_not_run)
    again = script.run(DESIGN, ENGINES, FREE, RATE, tmp_path, workers=1, allow_unmeasured=True)
    assert again["regimes"] == summary["regimes"]
