"""A complete synthetic `data/a4/analysis.json`, for the figure and post tests.

Not a test module. Its inputs come from tests/a4_stores.py's stores through
the real analysis script, and its sweep from tests/a4_evaluations.py's
`rich_sweep`, analysed at that sweep's 10 s SLO so the crossover has shape.
"""

import dataclasses
import importlib.util
from pathlib import Path

from a4_evaluations import DESIGN, RATE, SKEWS, rich_sweep
from a4_stores import write_stores

from placement.analysis import analyse

REPO = Path(__file__).resolve().parents[1]


def example_analysis(root: Path) -> dict:
    spec = importlib.util.spec_from_file_location("a4_analyse", REPO / "scripts" / "a4_analyse.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    reg = write_stores(root)
    script.a4_sweep.evaluations_for = lambda *a, **k: rich_sweep()
    result = script.analyse_all(reg, script.STORES, root=root,
                                a1_store=REPO / "data" / "campaign.jsonl",
                                sweep_out=root / "sweep", workers=1)
    result.update(analyse(rich_sweep(), dataclasses.replace(DESIGN, skews=SKEWS),
                          total_rate=5.0, output_len=256, rate=RATE,
                          reference={"regime": "bursty", "s": 1.0}))
    return result
