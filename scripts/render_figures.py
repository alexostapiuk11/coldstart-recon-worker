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
    annotate_first_touch,
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
    rows = annotate_first_touch([derive(r) for r in JsonlStore(args.store).read_all()])
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

    # Spec 5 requires first-touch and repeat-host runs to be reported
    # separately. A host that has never pulled the image pays for it in
    # t_platform: window 1's single first-touch run carried 2174 s against a
    # 65.7 s median, 17.8x the next slowest, and pooling it flattened every
    # real difference in the ECDF into the left edge of the plot. Only the
    # distribution figure is affected -- the waterfall and per-host figures
    # use medians, which absorb one outlier, and excluding runs from them
    # would understate what the campaign actually cost.
    ecdf_rows = [r for r in total_part.publishable if r.get("first_touch") is False]
    n_first_touch = len(total_part.publishable) - len(ecdf_rows)
    if n_first_touch:
        print(
            f"ecdf: excluding {n_first_touch} first-touch run(s), "
            f"plotting {len(ecdf_rows)} repeat-host runs"
        )

    for name, fn, plot_rows, part in [
        ("waterfall", figures.waterfall, total_part.publishable, total_part),
        ("warmup", figures.warmup_curve, warm_part.publishable, warm_part),
        ("ecdf", figures.ecdf_plot, ecdf_rows, total_part),
        ("per_host", figures.per_host_medians, total_part.publishable, total_part),
    ]:
        try:
            path = fn(plot_rows, out / f"{name}.png")
        except (ValueError, NotPublishableError) as exc:
            raise SystemExit(
                f"{name}: could not render from store {args.store!r}: {exc} "
                f"(plotted={len(plot_rows)}, publishable={len(part.publishable)}, "
                f"discarded={len(part.discarded)}, failed={len(part.failed)})"
            ) from exc
        print(f"{name}: {path} ({path.stat().st_size // 1024} KB, n={len(plot_rows)})")


if __name__ == "__main__":
    main()
