"""Render the four body figures from the stored campaign JSONL."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coldstart.analysis import figures
from coldstart.analysis.metrics import derive
from coldstart.analysis.pipeline import REQUIRED_FOR_T_TOTAL, REQUIRED_FOR_WARMUP, partition
from coldstart.store import JsonlStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/campaign.jsonl")
    ap.add_argument("--out", default="build/figures")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = [derive(r) for r in JsonlStore(args.store).read_all()]
    total = partition(rows, required=REQUIRED_FOR_T_TOTAL).publishable
    warm = partition(rows, required=REQUIRED_FOR_WARMUP).publishable

    for name, fn, src in [
        ("waterfall", figures.waterfall, total),
        ("warmup", figures.warmup_curve, warm),
        ("ecdf", figures.ecdf_plot, total),
        ("per_host", figures.per_host_medians, total),
    ]:
        path = fn(src, out / f"{name}.png")
        print(f"{name}: {path} ({Path(path).stat().st_size // 1024} KB, n={len(src)})")


if __name__ == "__main__":
    main()
