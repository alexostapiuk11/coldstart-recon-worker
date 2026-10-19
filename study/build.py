"""Build a unit's page and brief from its content.json."""

from __future__ import annotations

from pathlib import Path

from study.brief import render_brief
from study.page import render_page
from study.schema import validate
from study.trace import load

STUDY_DIR = Path(__file__).resolve().parents[1] / "docs" / "learning" / "study"


def build_unit(unit_dir: Path) -> tuple[str, str]:
    content = load(unit_dir)
    validate(content)
    return render_page(content), render_brief(content)
