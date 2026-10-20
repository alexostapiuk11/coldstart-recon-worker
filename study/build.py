"""Build a unit's pages and briefs from its content.json (and practice.json)."""

from __future__ import annotations

import json
from pathlib import Path

from study.brief import render_brief
from study.page import render_page
from study.practice import validate_practice
from study.practice_brief import render_practice_brief
from study.practice_page import render_practice_page
from study.schema import validate
from study.trace import load

STUDY_DIR = Path(__file__).resolve().parents[1] / "docs" / "learning" / "study"


def build_unit(unit_dir: Path) -> tuple[str, str]:
    content = load(unit_dir)
    validate(content)
    return render_page(content), render_brief(content)


def has_practice(unit_dir: Path) -> bool:
    return (unit_dir / "practice.json").is_file()


def build_practice(unit_dir: Path) -> tuple[str, str]:
    """(practice.html, practice-brief.md) for the unit in `unit_dir`. Another unit that a
    `review` or a link names is looked up next to it (a sibling folder)."""
    unit = load(unit_dir)
    validate(unit)
    practice = json.loads((unit_dir / "practice.json").read_text())

    def load_unit(unit_id: str) -> dict | None:
        path = unit_dir.parent / unit_id
        return load(path) if (path / "content.json").is_file() else None

    validate_practice(practice, unit, unit_dir.name, load_unit)
    return (render_practice_page(practice, unit, load_unit),
            render_practice_brief(practice, unit, load_unit))
