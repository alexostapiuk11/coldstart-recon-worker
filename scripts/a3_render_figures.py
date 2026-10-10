"""Render artifact 3's four figures from an analysis file.

    .venv/bin/python scripts/a3_render_figures.py --analysis data/a3/analysis.json --out docs/figures/a3

An analysis marked NOT_DATA (a stub) is refused unless --allow-stub is passed.
Also writes a 375 px wide `-phone.png` copy of each figure, which is what gets
looked at for legibility before a figure is called done.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from PIL import Image

from harness.figure_guards import PHONE_WIDTH_PX
from toolcall.figures import FIGURES, missing_paths


def phone_copy(src: Path) -> Path:
    dst = src.with_name(src.stem + "-phone.png")
    with Image.open(src) as im:
        height = round(im.height * PHONE_WIDTH_PX / im.width)
        im.resize((PHONE_WIDTH_PX, height), Image.LANCZOS).save(dst)
    return dst


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-stub", action="store_true",
                    help="draw a NOT_DATA stub analysis, to lay figures out")
    args = ap.parse_args(argv)
    analysis = json.loads(Path(args.analysis).read_text())
    if "NOT_DATA" in analysis:
        if not args.allow_stub:
            print(f"{args.analysis} is marked NOT_DATA ({analysis['NOT_DATA']}); "
                  "pass --allow-stub to draw it as a layout", file=sys.stderr)
            return 2
        print("NOT DATA: these figures are stub layouts, not results")
    missing = missing_paths(analysis)
    if missing:
        raise ValueError(
            f"{args.analysis} lacks {', '.join(missing)}: the analysis predates them and "
            "must be re-analysed before its figures are drawn")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, draw in FIGURES.items():
        path = out / f"{name}.png"
        plt.close(draw(analysis, path))
        print(f"[ok] {path} and {phone_copy(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
