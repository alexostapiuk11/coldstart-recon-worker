"""Write page.html and brief.md for every study unit (or the named ones), and
practice.html and practice-brief.md for each unit that has a practice.json.

    .venv/bin/python scripts/build_study.py [unit ...]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from study.build import STUDY_DIR, build_practice, build_unit, has_practice


def main(argv: list[str], study_dir: Path = STUDY_DIR) -> int:
    names = argv or sorted(p.parent.name for p in study_dir.glob("*/content.json"))
    for name in names:
        unit_dir = study_dir / name
        page, brief = build_unit(unit_dir)
        (unit_dir / "page.html").write_text(page)
        (unit_dir / "brief.md").write_text(brief)
        print(f"built {name}: {len(page):,} B page, {len(brief):,} B brief")
        if has_practice(unit_dir):
            practice, practice_brief = build_practice(unit_dir)
            (unit_dir / "practice.html").write_text(practice)
            (unit_dir / "practice-brief.md").write_text(practice_brief)
            print(f"built {name} practice: {len(practice):,} B page, "
                  f"{len(practice_brief):,} B brief")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
