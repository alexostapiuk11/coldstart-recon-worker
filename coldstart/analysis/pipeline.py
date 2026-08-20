"""The gate between stored rows and every consumer: `metrics.derive()` deliberately
returns two different row shapes (a 6-key row for a failed run, a full row for an ok
one) and `None` for fields it could not compute on an otherwise-ok run. Nothing used
to decide which rows were safe to hand to a figure or a stats call, so every consumer
invented its own error policy and each failed differently on the same bad input —
recorded as B4 in the plan.

`partition()` is the one function meant to sit between `[derive(r) for r in
store.read_all()]` and everything downstream. It does not hardcode one notion of
"publishable": the spec's clock-consistency discard rule, T_weights nullity, and
T_fast nullity are three different, independent reasons a row might not suit a given
analysis (an inconsistent run can still have a perfectly good `t_weights`; a merged
run can still have a perfectly good `t_total`), so the caller states which fields the
analysis at hand actually needs via `required` rather than this module guessing.

No imports from the rest of `coldstart.analysis` — `metrics.py` already imports
`stats.py`, and `figures.py` imports both, so keeping this module import-free avoids
adding a cycle and keeps it usable from any of them.
"""

from dataclasses import dataclass, field

# Presets for the analyses this plan actually builds. Each is just a `required`
# tuple `partition()` already knows how to interpret — these exist so a call site
# reads "what this analysis needs" rather than a bare tuple literal, and so the four
# figures / the T_weights contrast can't quietly drift from each other on what they
# require.
REQUIRED_FOR_WARMUP: tuple[str, ...] = ()
"""`warmup_curve` needs only a successful run — the warmup list lives on every ok
row regardless of whether the T_total/T_process clocks reconciled."""

REQUIRED_FOR_T_TOTAL: tuple[str, ...] = ("consistent",)
"""`waterfall`, `ecdf_plot`, and `per_host_medians` all read `t_total` and/or
`t_platform` — both `None` on a row that failed the clock-consistency check (spec
6.5 rule 3), so both need the row's `consistent` flag to be `True`, not merely
present."""

REQUIRED_FOR_T_WEIGHTS: tuple[str, ...] = ("t_weights",)
"""The primary A→B / B→C contrast (spec 7, Task 19). Deliberately does NOT also
require `"consistent"`: `t_weights` is S2+S3, computed and validated independently
of the T_total/T_process reconciliation, so a clock-skewed run can still carry a
perfectly good `t_weights` and there is no reason to discard it from this contrast
specifically."""

REQUIRED_FOR_T_FAST: tuple[str, ...] = ("t_fast_seconds",)
"""The T_fast / business-framing figures (economics.py). `t_fast_seconds` is
`None` on every run recorded before the Task 11 probe emits `t_dispatch_mono` on
its warmup records (see metrics.t_fast_seconds's docstring, B5) — today that is
every real run, so this preset legitimately discards most of a pre-Task-11
campaign, which is the honest state of the harness rather than a bug in this gate.
"""


class NotPublishableError(ValueError):
    """Raised by a figure or stats function when a row it was handed is not
    publishable for what that function needs. Names the row by the identity
    `metrics.derive()` actually threads through every row (`arm`/`host_id`/
    `triple_index` — `derive()` does not carry `run_id`) and the field or reason,
    instead of the bare `KeyError`/`TypeError` this replaces (B4)."""


@dataclass(frozen=True)
class PartitionResult:
    """`partition()`'s output. Every row from the input lands in exactly one of
    these three lists — see `partition`'s docstring for the rule."""

    publishable: list[dict] = field(default_factory=list)
    discarded: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)


def _row_identity(row: dict) -> str:
    return (
        f"arm={row.get('arm')!r} host_id={row.get('host_id')!r} "
        f"triple_index={row.get('triple_index')!r}"
    )


def _missing_required(row: dict, required: tuple[str, ...]) -> list[str]:
    """Which names in `required` this row fails. `"consistent"` is checked as
    `is True` — it is a bool present on every ok row, so a bare not-None check
    would never fire and the clock-consistency gate would silently do nothing.
    Every other name is checked the ordinary way: present and not `None`."""
    missing = []
    for name in required:
        if name == "consistent":
            if row.get("consistent") is not True:
                missing.append(name)
        elif row.get(name) is None:
            missing.append(name)
    return missing


def _exclusion_labels(row: dict, missing: list[str]) -> tuple[str, ...]:
    """One label per missing name, chosen so the reason is a small, tabulatable
    category and never the row's own free-form `inconsistency_reason` text (that
    string embeds the run's actual numbers, so grouping by it directly would put
    almost every row in its own bucket — useless for a discard-count table).
    `"consistent"` maps to the row's `discard_reason` (already the closed
    `checks.DiscardReason` enum); anything else maps to `"missing_<field>"`."""
    labels = []
    for name in missing:
        if name == "consistent":
            reason = row.get("discard_reason")
            labels.append(reason.value if reason is not None else "inconsistent")
        else:
            labels.append(f"missing_{name}")
    return tuple(labels)


def partition(rows, required: tuple[str, ...] = ()) -> PartitionResult:
    """Split `metrics.derive()` output into three buckets an analysis can trust.

    `rows` is the direct, unfiltered output of `derive()` — a mix of the 6-key row
    a failed run produces and the full row an ok run produces is exactly the input
    this function exists to handle; it is not a precondition violation.

    Each row lands in exactly one bucket:

    - `failed` — `row["ok"] is False`. Never entered into `publishable` or
      `discarded`: a failed run has no `t_total`/`t_weights`/decomposition to be
      discarded *from*, and folding it into "discarded" is exactly the conflation
      the plan flags (derive() sets `consistent=False` on failed rows too, so
      `not consistent` cannot be used to separate the failure rate from the
      discard rate). Feed this bucket to `failure_rate_by_arm`.
    - `discarded` — `ok`, but missing something `required` demands. Each row here
      is a shallow copy of the original derive() row with `"exclusion_reason"`
      (a comma-joined string) and `"exclusion_labels"` (its tuple form) added, so
      the reason travels with the row instead of being silently dropped. Feed this
      bucket to `discard_table`.
    - `publishable` — `ok`, and every name in `required` is satisfied. Safe to
      hand to a figure or a stats call that needs exactly those fields.

    See the module-level `REQUIRED_FOR_*` constants for the presets this plan's
    figures and stats calls actually use, and `_missing_required` for exactly what
    a name in `required` checks.
    """
    publishable: list[dict] = []
    discarded: list[dict] = []
    failed: list[dict] = []
    for row in rows:
        if row.get("ok") is False:
            failed.append(row)
            continue
        missing = _missing_required(row, required)
        if missing:
            labels = _exclusion_labels(row, missing)
            discarded.append(
                {**row, "exclusion_reason": ", ".join(labels), "exclusion_labels": labels}
            )
            continue
        publishable.append(row)
    return PartitionResult(publishable=publishable, discarded=discarded, failed=failed)


def failure_rate_by_arm(rows) -> dict[str, dict]:
    """Failure rate per arm, by `failure_class` — the first of the two tables spec
    6.6/8 requires reported alongside the latency numbers.

    `rows` is the FULL, unpartitioned `derive()` output for a campaign (both ok and
    failed rows) — a rate needs the total run count as its denominator, which the
    `failed` bucket alone does not carry.

    Returns `{arm: {"total": n, "failed": k, "rate": k / n, "by_class": {class:
    count}}}` for every arm that appears in `rows` at all.

    Deliberately reads only `row.get("ok") is False`, never `consistent`: a failed
    run's `consistent` field is always `False` too (derive() sets it on the 6-key
    row for exactly this reason — it never reached a state where consistency could
    even be evaluated), so using it here would silently fold discards into the
    failure rate. Discards are `discard_table`'s job, computed from a disjoint row
    population (`partition()`'s `discarded` bucket only ever contains `ok` rows) —
    the separation B4 requires.
    """
    out: dict[str, dict] = {}
    for row in rows:
        arm = row["arm"]
        entry = out.setdefault(arm, {"total": 0, "failed": 0, "by_class": {}})
        entry["total"] += 1
        if row.get("ok") is False:
            entry["failed"] += 1
            cls = row.get("failure_class") or "unknown"
            entry["by_class"][cls] = entry["by_class"].get(cls, 0) + 1
    for entry in out.values():
        entry["rate"] = entry["failed"] / entry["total"]
    return out


def discard_table(discarded_rows) -> dict[str, dict]:
    """Discard count per arm, by reason — the second of the two tables spec 6.6/8
    requires, and the one `consistent=False` used to conflate with the failure
    rate (B4). `discarded_rows` is `partition()`'s `discarded` bucket specifically:
    every row in it is `ok`, so nothing here can double-count a run
    `failure_rate_by_arm` already counted.

    Returns `{arm: {"total": n, "by_reason": {reason: count}}}` for every arm that
    appears among `discarded_rows`. `reason` is the row's `exclusion_reason` — see
    `_exclusion_labels` for how it is chosen.
    """
    out: dict[str, dict] = {}
    for row in discarded_rows:
        arm = row["arm"]
        entry = out.setdefault(arm, {"total": 0, "by_reason": {}})
        entry["total"] += 1
        reason = row["exclusion_reason"]
        entry["by_reason"][reason] = entry["by_reason"].get(reason, 0) + 1
    return out
