"""Render the five figures of artifact 2's post, and their phone copies.

    .venv/bin/python scripts/a2_render_post_figures.py [--out docs/figures/a2] [--phone]

Four come from `data/a2/post-analysis.json` (`autoscale.figures_a2_post`), the
fifth is the measured service curve (`data/a2/service-curve.json`) drawn by
`autoscale.figures.service_curve` exactly as `scripts/a2_render_figures.py`
draws it: through `select_curve`, so the idle point and the `measured=` bars
are the draft script's, not a second reading of the file. Those two files are
all this script reads. It spends nothing and runs no sweep, which is what lets
`tests/test_a2_published_figures.py` re-render it on every test run and compare
bytes with what the post links.

`--phone` also writes `<name>-phone.png`, the figure downscaled to 375 px wide
(the width the post is read at on a phone) so it can be looked at. LANCZOS in
PIL, not the matplotlib re-draw `scripts/a4_render_figures.py` uses: a re-draw
resamples with matplotlib's own interpolation and then re-encodes through a
figure, where the point of the copy is only to show what a 375 px browser
resize of the PNG looks like. Phone copies are off by default because the
byte-for-byte test compares only the desktop files.

`--out` defaults to the published directory, anchored at the repo root and not
the working directory, so running this from elsewhere cannot scatter PNGs.
Rendering is byte-deterministic (nothing here is random or timestamped; run it
twice and `cmp` the files), which is what makes the exact comparison possible.
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import matplotlib

matplotlib.use("Agg")

from PIL import Image

from autoscale.figures import service_curve
from autoscale.figures_a2_post import (
    host_speed,
    load_balancer,
    simulator_answer,
    validation_attempts,
)
from autoscale.measured_curve import DEFAULT_PATH, select_curve

ANALYSIS = REPO / "data" / "a2" / "post-analysis.json"
DEFAULT_OUT = REPO / "docs" / "figures" / "a2"
PHONE_WIDTH_PX = 375

# File stem -> drawing function over the parsed analysis. The stems are the
# names the post links; "attempts" is shorter than its function's name on purpose.
ANALYSIS_FIGURES = {
    "attempts": validation_attempts,
    "load_balancer": load_balancer,
    "host_speed": host_speed,
    "simulator_answer": simulator_answer,
}


def phone_copy(src: Path, dst: Path) -> Path:
    with Image.open(src) as img:
        w, h = img.size
        img.resize((PHONE_WIDTH_PX, round(h * PHONE_WIDTH_PX / w)), Image.LANCZOS).save(dst)
    return dst


def main(argv=None) -> list[Path]:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--phone", action="store_true",
                    help="also write <name>-phone.png, 375 px wide")
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    analysis = json.loads(ANALYSIS.read_text())
    written = [draw(analysis, out / f"{name}.png") for name, draw in ANALYSIS_FIGURES.items()]
    curve, measured = select_curve(REPO / DEFAULT_PATH, placeholder=False)
    written.append(service_curve(curve, out / "service_curve.png", measured=measured))
    written = [Path(p) for p in written]
    if args.phone:
        written += [phone_copy(p, p.with_name(f"{p.stem}-phone.png")) for p in list(written)]
    for p in written:
        print(f"wrote {p}")
    return written


if __name__ == "__main__":
    main()
