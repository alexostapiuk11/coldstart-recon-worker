"""Write page.html and brief.md for every study unit (or the named ones).

    .venv/bin/python scripts/build_study.py [unit ...]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from study.build import STUDY_DIR, build_unit


def main(argv: list[str]) -> int:
    names = argv or sorted(p.parent.name for p in STUDY_DIR.glob("*/content.json"))
    for name in names:
        page, brief = build_unit(STUDY_DIR / name)
        (STUDY_DIR / name / "page.html").write_text(page)
        (STUDY_DIR / name / "brief.md").write_text(brief)
        print(f"built {name}: {len(page):,} B page, {len(brief):,} B brief")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
