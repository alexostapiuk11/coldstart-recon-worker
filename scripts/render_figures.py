"""Render the four body figures from the stored campaign JSONL."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coldstart.analysis import figures
from coldstart.analysis.metrics import derive
from coldstart.analysis.pipeline import (
    REQUIRED_FOR_T_TOTAL,
    REQUIRED_FOR_WARMUP,
    NotPublishableError,
    partition,
)
from coldstart.store import JsonlStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/campaign.jsonl")
    ap.add_argument("--out", default="build/figures")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = [derive(r) for r in JsonlStore(args.store).read_all()]
    # Kept as two separately-named PartitionResults (not collapsed into one
    # call) even though REQUIRED_FOR_T_TOTAL and REQUIRED_FOR_WARMUP are both
    # `("consistent",)` today, so `total_part` and `warm_part` gate identical
    # rows right now. That agreement is incidental, not structural -- see the
    # REQUIRED_FOR_* docstrings in pipeline.py -- and `warmup_curve` must keep
    # tracking REQUIRED_FOR_WARMUP specifically, not whatever preset the
    # T_total figures happen to use. If this were "simplified" to a single
    # partition shared by all four figures, the day the two presets diverge
    # `warmup_curve` would silently start being gated by the wrong
    # requirement -- a defect no test and no rendered PNG would reveal until
    # the data actually exercised the difference.
    total_part = partition(rows, required=REQUIRED_FOR_T_TOTAL)
    warm_part = partition(rows, required=REQUIRED_FOR_WARMUP)

    for name, fn, part in [
        ("waterfall", figures.waterfall, total_part),
        ("warmup", figures.warmup_curve, warm_part),
        ("ecdf", figures.ecdf_plot, total_part),
        ("per_host", figures.per_host_medians, total_part),
    ]:
        try:
            path = fn(part.publishable, out / f"{name}.png")
        except (ValueError, NotPublishableError) as exc:
            raise SystemExit(
                f"{name}: could not render from store {args.store!r}: {exc} "
                f"(publishable={len(part.publishable)}, discarded={len(part.discarded)}, "
                f"failed={len(part.failed)})"
            ) from exc
        print(
            f"{name}: {path} ({path.stat().st_size // 1024} KB, n={len(part.publishable)})"
        )


if __name__ == "__main__":
    main()
