"""Render artifact 4's four figures, and their phone-width inspection copies,
from data/a4/analysis.json. Spends nothing.

    .venv/bin/python scripts/a4_render_figures.py [--analysis data/a4/analysis.json] \\
        [--out build/a4-figures]

Writes <name>.png and <name>-phone.png for each figure. The phone copy is the
figure downscaled to 375 px wide, the width the post is read at on a phone,
made the way artifact 1's runbook makes its own (docs/runbook.md). It exists
to be LOOKED AT: the tests check text sizes and positions, not whether the
chart reads.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib.image as mpimg
import matplotlib.pyplot as plt

from harness.figure_guards import PHONE_WIDTH_PX
from placement.figures import FIGURES


def phone_copy(src: Path, dst: Path) -> Path:
    img = mpimg.imread(src)
    h, w = img.shape[0], img.shape[1]
    fig = plt.figure(figsize=(PHONE_WIDTH_PX / 100, PHONE_WIDTH_PX / 100 * h / w), dpi=100)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.imshow(img)
    ax.axis("off")
    fig.savefig(dst, dpi=100)
    plt.close(fig)
    return dst


def main(argv=None) -> list[Path]:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--analysis", default="data/a4/analysis.json")
    ap.add_argument("--out", default="build/a4-figures")
    args = ap.parse_args(argv)
    analysis = json.loads(Path(args.analysis).read_text())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, draw in FIGURES.items():
        path = draw(analysis, out / f"{name}.png")
        written += [path, phone_copy(path, out / f"{name}-phone.png")]
        print(f"wrote {path} and its phone copy")
    return written


if __name__ == "__main__":
    main()
