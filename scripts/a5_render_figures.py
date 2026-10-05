"""Render artifact 5's four figures from an analysis file.

    .venv/bin/python scripts/a5_render_figures.py --analysis data/a5/analysis.json --out build/a5-figures

Also writes a 375 px wide `-phone.png` copy of each figure, which is what gets
looked at for legibility before a figure is called done.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib.pyplot as plt
from PIL import Image

from harness.figure_guards import PHONE_WIDTH_PX
from multilora.figures import FIGURES


def phone_copy(src: Path) -> Path:
    """Downscale to the width `harness.figure_guards` calibrates legibility at."""
    dst = src.with_name(src.stem + "-phone.png")
    with Image.open(src) as im:
        height = round(im.height * PHONE_WIDTH_PX / im.width)
        im.resize((PHONE_WIDTH_PX, height), Image.LANCZOS).save(dst)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    analysis = json.loads(Path(args.analysis).read_text())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, draw in FIGURES.items():
        if name == "cost_per_tenant" and "cost_table" not in analysis:
            print(f"[skip] {name}: no cost table (artifact 4 results not supplied)")
            continue
        path = out / f"{name}.png"
        plt.close(draw(analysis, path))
        print(f"[ok] {path} and {phone_copy(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
