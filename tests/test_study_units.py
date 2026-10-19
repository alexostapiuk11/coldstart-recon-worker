import pytest

from study.build import STUDY_DIR, build_unit
from study.trace import load, missing_sections, untraced_numbers

UNITS = sorted(p.parent for p in STUDY_DIR.glob("*/content.json"))
IDS = [u.name for u in UNITS]


@pytest.mark.parametrize("unit", UNITS, ids=IDS)
def test_outputs_are_in_sync_with_content(unit):
    page, brief = build_unit(unit)
    assert (unit / "page.html").read_text() == page, "run scripts/build_study.py"
    assert (unit / "brief.md").read_text() == brief, "run scripts/build_study.py"


@pytest.mark.parametrize("unit", UNITS, ids=IDS)
def test_every_number_traces_to_a_cited_source(unit):
    assert untraced_numbers(load(unit)) == []


@pytest.mark.parametrize("unit", UNITS, ids=IDS)
def test_every_cited_section_exists(unit):
    assert missing_sections(load(unit)) == []
