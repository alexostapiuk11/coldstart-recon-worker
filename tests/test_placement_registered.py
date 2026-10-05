"""Step 2's committed values are the pre-registered rules applied to the
committed reconnaissance report and screen, and nothing else.

`placement/registered.py`, the design files and the "Step 2, part 2" section
of `docs/experiment-a4.md` were all written by `scripts/a4_step2.py values`.
This re-derives every value, so a hand edit to any of the three, or a change
to a rule after the values were committed, fails here."""

import json
import re
from pathlib import Path

from placement import registered
from placement.registration import SECTION, design_files, mismatches, render_doc, values
from placement.screen import choose
from placement.step2 import measurement_design

REPO = Path(__file__).resolve().parents[1]
REPORT = json.loads((REPO / "fixtures" / "a4" / "recon-report.json").read_text())
SCREEN = json.loads((REPO / "data" / "a4" / "screen.json").read_text())
DOC = (REPO / "docs" / "experiment-a4.md").read_text()


def _committed() -> dict:
    return {k: getattr(registered, k) for k in dir(registered) if k.isupper()}


def _expected() -> dict:
    return values(measurement_design(REPORT), SCREEN, rate=registered.GPU_HOURLY_RATE,
                  provenance=registered.RATE_PROVENANCE)


def test_the_registered_values_are_the_rules_applied_to_the_inputs():
    assert mismatches(_committed(), _expected()) == []


def test_the_screens_recorded_choice_is_its_best_candidate():
    best = choose(SCREEN["candidates"])
    assert SCREEN["chosen"] == {"offered_gpus": best["offered_gpus"],
                                "slo_swap_multiple": best["slo_swap_multiple"]}


def test_the_design_files_are_the_registered_designs():
    for name, design in design_files(measurement_design(REPORT)).items():
        committed = json.loads((REPO / "data" / "a4" / "designs" / f"{name}.json").read_text())
        assert committed == json.loads(json.dumps(design)), name


def test_the_document_states_the_values_verbatim():
    assert DOC.count(SECTION) == 1
    date = re.search(r"Committed (\d{4}-\d{2}-\d{2})\.", DOC[DOC.index(SECTION):]).group(1)
    assert render_doc(_committed(), date) in DOC
