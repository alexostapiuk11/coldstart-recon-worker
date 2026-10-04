"""Input guards and legibility constants every artifact's figures share.

The four figure constraints repeat verbatim across all five artifact specs:
N stated, no truncated axes, intervals shown, legible on a phone. Two of those
are enforceable in code and are enforced here -- an empty input raises rather
than drawing an empty axes, and a group missing from the data raises rather
than quietly producing a chart that compares two conditions where the reader
believes three were compared.

`PHONE_WIDTH_PX` / `phone_pt` exist because this repo has already shipped that
defect once: a figure that is illegible on a phone still renders, still passes
every assertion about its data, and looks fine on the laptop it was written on.
"""

from harness.publish import NotPublishableError

# Phone legibility, as arithmetic instead of guesswork.
#
# These figures are published in a post most readers open on a phone, where the
# PNG is scaled to the viewport width. What survives that downscale is not a
# font's absolute point size but its size *relative to the figure*: rendering
# DPI cancels out, leaving
#
#     rendered_px = pt * PHONE_WIDTH_PX / (72 * figure_width_in)
#
# The consequence is counterintuitive and this module has been caught by it
# twice: making a crowded chart *wider* to fit its legend makes every label
# smaller on a phone. Widening must be paid for with a proportional font
# increase, or the room gained is cancelled exactly.
#
# MIN_PHONE_TEXT_PX is calibrated against rendered output, not taste: at the
# 300-run campaign's figures, 8pt legends on an 8-inch canvas (5.2px) and 11pt
# arm labels on a 10.9-inch canvas (5.3px) were both unreadable at phone width,
# while a 12pt callout on an 8-inch canvas (7.8px) was comfortable. The floor
# sits just below the latter. `test_figures.py` asserts every text artist in
# all four figures clears it, so this cannot regress silently -- which it did
# before, because a figure that is illegible on a phone still renders, still
# passes every assertion about its data, and looks fine on the laptop where it
# was written.
PHONE_WIDTH_PX = 375
MIN_PHONE_TEXT_PX = 7.5

# Fields tried, in order, when naming a row in an error message. A row carries
# whichever of these its artifact defines; the identity is for a human reading
# a traceback, so an absent field is skipped rather than raising inside the
# error path itself.
IDENTITY_FIELDS = ("arm", "condition", "regime", "signal", "host_id", "triple_index")


def phone_pt(px: float, fig_width_in: float) -> float:
    """Point size that renders at `px` pixels when a `fig_width_in`-wide figure
    is displayed `PHONE_WIDTH_PX` wide. Inverse of the relation above."""
    return px * 72 * fig_width_in / PHONE_WIDTH_PX


def row_identity(row: dict, fields: tuple[str, ...] = IDENTITY_FIELDS) -> str:
    """Name a row for an error message, using whichever identity fields it has."""
    present = [f"{f}={row[f]!r}" for f in fields if f in row]
    return " ".join(present) if present else "row with no identity fields"


def required_field(row: dict, key: str):
    """Raise `NotPublishableError`, naming the row and `key`, in place of the
    bare `KeyError` (key absent -- a failed run's short row) or `TypeError`
    (key present but `None` -- an inconsistent or merged run) that
    dereferencing `row[key]` directly would produce deep inside a median or
    ECDF call. B4 in the artifact 1 plan."""
    if key not in row:
        raise NotPublishableError(
            f"row ({row_identity(row)}) has no {key!r} field -- route rows "
            "through harness.publish.partition() with that field in "
            "`required` before calling this figure"
        )
    val = row[key]
    if val is None:
        raise NotPublishableError(
            f"row ({row_identity(row)}) has {key!r} = None -- not publishable "
            "for this figure; route rows through harness.publish.partition() "
            "with that field in `required` first"
        )
    return val


def validate_rows(rows) -> list[dict]:
    """Fail loudly on the one input domain every figure shares: nothing to plot.

    A copy is returned so callers get a stable list even if `rows` was a
    generator (no figure consumes `rows` more than once, but this keeps that
    assumption from becoming load-bearing by accident)."""
    rows = list(rows)
    if not rows:
        raise ValueError("rows must not be empty")
    return rows


def group_required(rows, key: str, expected) -> dict[str, list[dict]]:
    """Split rows by `row[key]`, requiring every value in `expected` to appear.

    Silently skipping a missing group (`if not rs: continue`) would drop that
    group's whole series from the chart with no indication anything was wrong --
    a figure that quietly compares two conditions instead of three is a
    misleading chart, not a smaller one. Insertion order follows `expected`, so
    a caller controls series order by ordering that tuple."""
    rows = validate_rows(rows)
    by = {v: [r for r in rows if r[key] == v] for v in expected}
    missing = [v for v in expected if not by[v]]
    if missing:
        raise ValueError(
            f"no rows for {key} {missing}; refusing to silently drop "
            f"{'a series' if len(missing) == 1 else 'series'} from the chart"
        )
    return by
