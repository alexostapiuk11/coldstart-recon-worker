import json
from pathlib import Path

import pytest

from study.build import STUDY_DIR, build_practice, build_unit, has_practice
from study.trace import (
    evidence_commits,
    load,
    missing_commits,
    missing_sections,
    untraced_numbers,
    untraced_practice_numbers,
)

ROOT = Path(__file__).resolve().parents[1]

UNITS = sorted(p.parent for p in STUDY_DIR.glob("*/content.json"))
IDS = [u.name for u in UNITS]


@pytest.mark.parametrize("unit", UNITS, ids=IDS)
def test_outputs_are_in_sync_with_content(unit):
    page, brief = build_unit(unit)
    assert (unit / "page.html").read_text() == page, "run scripts/build_study.py"
    assert (unit / "brief.md").read_text() == brief, "run scripts/build_study.py"


@pytest.mark.parametrize("unit", UNITS, ids=IDS)
def test_practice_outputs_exist_only_with_a_practice_json_and_are_in_sync(unit):
    files = [unit / "practice.html", unit / "practice-brief.md"]
    if not has_practice(unit):
        assert [f.name for f in files if f.exists()] == [], (
            "practice.json is gone; delete the generated practice files")
        return
    page, brief = build_practice(unit)
    assert files[0].read_text() == page, "run scripts/build_study.py"
    assert files[1].read_text() == brief, "run scripts/build_study.py"


@pytest.mark.parametrize("unit", UNITS, ids=IDS)
def test_every_practice_number_traces_to_the_units_sources_or_is_declared(unit):
    if not has_practice(unit):
        return
    practice = json.loads((unit / "practice.json").read_text())
    assert untraced_practice_numbers(practice, load(unit)) == []


@pytest.mark.parametrize("unit", UNITS, ids=IDS)
def test_every_number_traces_to_a_cited_source(unit):
    assert untraced_numbers(load(unit)) == []


@pytest.mark.parametrize("unit", UNITS, ids=IDS)
def test_every_cited_section_exists(unit):
    assert missing_sections(load(unit)) == []


@pytest.mark.parametrize("unit", UNITS, ids=IDS)
def test_every_evidence_commit_exists_in_its_repo(unit):
    content = load(unit)
    if not evidence_commits(content):
        pytest.skip(f"{unit.name} cites no evidence commits")
    missing, unavailable = missing_commits(content, ROOT)
    assert missing == [], "evidence commits not found"
    if unavailable:
        pytest.skip("could not check every evidence commit: " + "; ".join(unavailable))
