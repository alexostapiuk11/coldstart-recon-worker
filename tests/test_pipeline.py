"""Tests for the publishability gate (B4): the missing stage between stored rows
and every consumer (figures, stats, the Task 19 pooling snippet).

The recurring defect on this plan was a fixture of all-clean rows testing a gate
whose entire job is exclusion. `_CAMPAIGN` below is one mixed campaign built through
real `RunRecord` -> `derive()` round trips (never hand-typed derived dicts) covering,
in one fixture: multiple clean successful runs across all three arms (enough to form
two complete within-host triples), a failed run, a clock-inconsistent run, an
engine-merged run with `t_weights is None`, and a run built the way the spec says
every real run looks before Task 11 ships -- `t_fast_seconds is None` for want of a
`t_dispatch_mono` offset (B5). Every count below is a literal, arrived at by
construction (which rows I put in which bucket), not by re-running derive()'s or
partition()'s own formula.
"""

import pytest

from coldstart.analysis.metrics import derive
from coldstart.analysis.pipeline import (
    REQUIRED_FOR_T_COMPILE,
    REQUIRED_FOR_T_FAST,
    REQUIRED_FOR_T_TOTAL,
    REQUIRED_FOR_T_WEIGHTS,
    REQUIRED_FOR_WARMUP,
    NotPublishableError,
    discard_table,
    failure_rate_by_arm,
    partition,
)
from coldstart.analysis.stats import bootstrap_median_diff, within_host_triples
from coldstart.checks import DiscardReason
from coldstart.schema import RunRecord

# Ten distinct per-request latencies with a non-flat tail -- copied from
# tests/test_metrics.py's fixture so steady state (median of the last three =
# 3.2) and the fast-tolerance index (6, latency 3.4) are pinned to known values
# that this file's own comments can refer back to.
_WARMUP_LATENCIES = [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 3.4, 4.0, 3.2, 2.0]
_S4_SUBPHASES = {"S4a": 3.0, "S4b": 20.0, "S4c": 4.0, "S4d": 2.0, "S4e": 5.0}

# The "simple" mark set every clean/inconsistent/merged row below starts from --
# identical to tests/test_metrics.py's `make()` default, already proven consistent
# by that file's tests (t_total=122.0, t_process=102.0, t_weights=50.0,
# t_s4_bracket=36.0, consistent=True). No warmup record carries `t_dispatch_mono`,
# so every row built from this set gets `t_fast_seconds=None` -- the pre-Task-11
# state B5 describes as "today, every real run."
_SIMPLE_MARKS = [
    {"stage": "S1_imports_done", "t_mono": 4.0},
    {"stage": "S2_acquisition_start", "t_mono": 4.0},
    {"stage": "S3_load_done", "t_mono": 54.0},
    {"stage": "S4_start", "t_mono": 54.0},
    {"stage": "S4_end", "t_mono": 90.0},
    {"stage": "S5_ready", "t_mono": 100.0},
    {"stage": "S6_request1_dispatch", "t_mono": 100.0},
    {"stage": "S6_first_token", "t_mono": 102.0},
    {"stage": "S7_warmup_done", "t_mono": 130.0},
]


def _simple_warmup() -> list[dict]:
    return [{"req_index": i, "ttft": 0.5, "end_to_end": v} for i, v in enumerate(_WARMUP_LATENCIES)]


def _record(
    arm: str,
    run_id: str,
    host_id: str,
    triple_index: int,
    *,
    outcome: str = "ok",
    failure_class: str | None = None,
    marks=None,
    warmup=None,
    t_submit: float = 0.0,
    t_result: float = 150.0,
    s4_subphases: dict | None = None,
) -> RunRecord:
    if outcome != "ok":
        return RunRecord(
            run_id=run_id,
            run_index=0,
            arm=arm,
            clock_A={"t_submit": t_submit, "t_result": t_result},
            clock_C={},
            clock_B={"t0_wall": 0.0, "marks": []},
            warmup=[],
            engine={},
            host={"host_id": host_id, "triple_index": triple_index},
            config={},
            status={"outcome": "failed", "failure_class": failure_class, "failure_detail": failure_class},
        )
    return RunRecord(
        run_id=run_id,
        run_index=0,
        arm=arm,
        clock_A={"t_submit": t_submit, "t_result": t_result},
        clock_C={},
        clock_B={"t0_wall": 0.0, "marks": _SIMPLE_MARKS if marks is None else marks},
        warmup=_simple_warmup() if warmup is None else warmup,
        engine={
            "kv_cache_blocks": 8192,
            "block_size": 16,
            "s4_subphases": dict(_S4_SUBPHASES) if s4_subphases is None else s4_subphases,
        },
        host={"host_id": host_id, "triple_index": triple_index},
        config={},
        status={"outcome": "ok", "failure_class": None, "failure_detail": None},
    )


def _dispatch_marks_and_warmup() -> tuple[list[dict], list[dict]]:
    """The one row (A5) built with a full `t_dispatch_mono` offset on every warmup
    record -- the only row in `_CAMPAIGN` for which `t_fast_seconds` is not `None`.
    `S7_warmup_done` is raised to 165.0 (from the simple set's 130.0) because a
    *real* cumulative dispatch schedule -- each request's own start time, not a
    near-zero gap -- runs well past 130.0 by request 10; using the simple set's
    value here would make S7 precede the last request's own completion, which
    derive() correctly refuses to accept.
    """
    marks = [
        {"stage": "S1_imports_done", "t_mono": 4.0},
        {"stage": "S2_acquisition_start", "t_mono": 4.0},
        {"stage": "S3_load_done", "t_mono": 54.0},
        {"stage": "S4_start", "t_mono": 54.0},
        {"stage": "S4_end", "t_mono": 90.0},
        {"stage": "S5_ready", "t_mono": 100.0},
        {"stage": "S6_request1_dispatch", "t_mono": 100.0},
        {"stage": "S6_first_token", "t_mono": 102.0},
        {"stage": "S7_warmup_done", "t_mono": 165.0},
    ]
    dispatch = 100.0
    warmup = []
    for i, latency in enumerate(_WARMUP_LATENCIES):
        warmup.append(
            {"req_index": i, "ttft": 0.5, "end_to_end": latency, "t_dispatch_mono": dispatch}
        )
        dispatch += latency + 0.5  # a real, non-zero gap between requests
    return marks, warmup


_A5_MARKS, _A5_WARMUP = _dispatch_marks_and_warmup()

_RECORDS = [
    # Triple 0, host h1: complete, all clean.
    _record("A", "r-a1", "h1", 0),
    _record("B", "r-b1", "h1", 0),
    _record("C", "r-c1", "h1", 0),
    # Triple 1, host h2: complete, all clean.
    _record("A", "r-a2", "h2", 1),
    _record("B", "r-b2", "h2", 1),
    _record("C", "r-c2", "h2", 1),
    # Triple 2, host h3: arm B failed -- looks complete by triple_index/host_id
    # alone, which is exactly the shape that used to sneak into
    # within_host_triples before the B4 fix.
    _record("A", "r-a3", "h3", 2),
    _record("B", "r-b3", "h3", 2, outcome="failed", failure_class="oom"),
    _record("C", "r-c3", "h3", 2),
    # Triple 6, host h4: clock-inconsistent (t_result=50.0 <-> t_process=102.0
    # trips PROCESS_EXCEEDS_TOTAL -- tests/test_metrics.py's own fixture for
    # this). t_weights is still perfectly valid: consistency and T_weights are
    # orthogonal, which is the whole reason partition() takes a `required` tuple
    # instead of one hardcoded predicate.
    _record("C", "r-c4", "h4", 6, t_result=50.0),
    # Triple 7, host h5: engine-merged, S3_load_done never delineated -> t_weights
    # is None. Still clock-consistent.
    _record(
        "A",
        "r-a4",
        "h5",
        7,
        marks=[m for m in _SIMPLE_MARKS if m["stage"] != "S3_load_done"],
    ),
    # Triple 9, host h7: the one row with a real t_dispatch_mono offset, so the
    # only row for which t_fast_seconds is not None.
    _record("A", "r-a5", "h7", 9, marks=_A5_MARKS, warmup=_A5_WARMUP, t_result=203.0),
]


def _campaign() -> list[dict]:
    return [derive(r) for r in _RECORDS]


# ---------------------------------------------------------------------------
# fixture sanity -- pin the shape of the fixture itself before trusting any
# assertion built on top of it
# ---------------------------------------------------------------------------


def test_fixture_sanity_twelve_records_one_failed():
    rows = _campaign()
    assert len(rows) == 12
    assert sum(1 for r in rows if r["ok"] is False) == 1
    assert sum(1 for r in rows if r["ok"] is True) == 11


def test_fixture_sanity_exactly_one_row_has_t_weights_none():
    rows = _campaign()
    assert sum(1 for r in rows if r["ok"] and r["t_weights"] is None) == 1


def test_fixture_sanity_exactly_one_row_is_inconsistent():
    rows = _campaign()
    inconsistent = [r for r in rows if r["ok"] and not r["consistent"]]
    assert len(inconsistent) == 1
    assert inconsistent[0]["discard_reason"] == DiscardReason.PROCESS_EXCEEDS_TOTAL
    assert inconsistent[0]["t_weights"] == pytest.approx(50.0)  # valid despite the flag


def test_fixture_sanity_exactly_one_row_has_t_fast_seconds():
    rows = _campaign()
    have_fast = [r for r in rows if r["ok"] and r["t_fast_seconds"] is not None]
    assert len(have_fast) == 1
    assert have_fast[0]["arm"] == "A"
    assert have_fast[0]["host_id"] == "h7"


# ---------------------------------------------------------------------------
# partition() -- publishability depends on the metric
# ---------------------------------------------------------------------------


def test_partition_warmup_preset_excludes_the_failed_run_and_the_inconsistent_row():
    """Second ruling on the same principle as the t_weights case below:
    warmup latencies are pure clock-B measurements with no cross-clock step
    of their own, which argues an inconsistent run's warmup data should
    still be trustworthy -- that argument was made and overruled (see
    REQUIRED_FOR_WARMUP's docstring): "clock A misbehaved, the rest is fine"
    and "this run is anomalous in ways nobody understands" are
    indistinguishable after the fact, so h4 is discarded here too, not kept
    because its warmup list still looks plausible. Same treatment as h4
    under REQUIRED_FOR_T_WEIGHTS: pinned landing in `discarded`, by name,
    with its reason -- not merely absent from `publishable`."""
    result = partition(_campaign(), required=REQUIRED_FOR_WARMUP)
    assert len(result.publishable) == 10
    assert len(result.discarded) == 1
    assert len(result.failed) == 1

    (row,) = result.discarded
    assert row["host_id"] == "h4"
    assert row["arm"] == "C"
    assert row["warmup"] is not None  # the data that "looks fine" -- discarded anyway
    assert row["exclusion_reason"] == DiscardReason.PROCESS_EXCEEDS_TOTAL.value
    assert row["exclusion_labels"] == (DiscardReason.PROCESS_EXCEEDS_TOTAL.value,)
    assert "h4" not in {r["host_id"] for r in result.publishable}


def test_partition_t_total_preset_excludes_the_inconsistent_row_only():
    result = partition(_campaign(), required=REQUIRED_FOR_T_TOTAL)
    assert len(result.publishable) == 10
    assert len(result.discarded) == 1
    assert len(result.failed) == 1
    assert result.discarded[0]["host_id"] == "h4"
    assert result.discarded[0]["arm"] == "C"


def test_partition_t_weights_preset_excludes_the_merged_row_and_the_inconsistent_row():
    """Ruling on B4's original design note: consistency is a baseline
    requirement for every published quantity, not a per-metric option (see
    REQUIRED_FOR_T_WEIGHTS's docstring). A run that failed the T_total/
    T_process consistency check is not trustworthy, full stop -- keeping the
    parts of it that still look plausible (here, a perfectly good t_weights
    on host h4) is exactly the selective inclusion pre-registration exists
    to prevent. h4 must land in `discarded`, specifically, not merely be
    absent from `publishable` -- this is the test that pins the ruling."""
    result = partition(_campaign(), required=REQUIRED_FOR_T_WEIGHTS)
    assert len(result.publishable) == 9
    assert len(result.discarded) == 2
    assert len(result.failed) == 1

    discarded_by_host = {r["host_id"]: r for r in result.discarded}
    assert set(discarded_by_host) == {"h4", "h5"}

    # h4: clock-inconsistent, t_weights otherwise valid -- excluded on
    # consistency alone, not on t_weights.
    h4 = discarded_by_host["h4"]
    assert h4["arm"] == "C"
    assert h4["t_weights"] == pytest.approx(50.0)  # still a real, plausible value
    assert h4["exclusion_labels"] == (DiscardReason.PROCESS_EXCEEDS_TOTAL.value,)

    # h5: the engine-merged run -- excluded on t_weights alone, still
    # clock-consistent.
    h5 = discarded_by_host["h5"]
    assert h5["arm"] == "A"
    assert h5["consistent"] is True
    assert h5["exclusion_labels"] == ("missing_t_weights",)

    assert "h4" not in {r["host_id"] for r in result.publishable}


def test_partition_t_compile_preset_excludes_a_merged_s4b_row_and_the_inconsistent_row():
    """Same ruling as REQUIRED_FOR_T_WEIGHTS, applied to `t_compile`
    (`subphase_values["S4b"]` in metrics.derive()): it is computed
    independently of the T_total/T_process consistency check, so a
    clock-inconsistent run's otherwise-plausible `t_compile` must still be
    discarded, and a run whose engine never delineated S4b (the same
    "merged phase" nullity condition already applied to t_weights, not a
    new one) is excluded on `t_compile` alone while remaining
    clock-consistent -- mirroring h4/h5 above exactly, one bracket over."""
    clean = derive(_record("B", "r-tc-ok", "h40", 40))
    merged = derive(
        _record(
            "B",
            "r-tc-merged",
            "h41",
            41,
            s4_subphases={k: v for k, v in _S4_SUBPHASES.items() if k != "S4b"},
        )
    )
    inconsistent = derive(_record("B", "r-tc-bad", "h42", 42, t_result=50.0))

    assert clean["t_compile"] is not None
    assert merged["t_compile"] is None
    assert merged["consistent"] is True  # excluded on t_compile alone, not consistency
    assert inconsistent["t_compile"] is not None  # still a real, plausible value
    assert inconsistent["consistent"] is False

    result = partition([clean, merged, inconsistent], required=REQUIRED_FOR_T_COMPILE)
    assert result.publishable == [clean]
    assert len(result.discarded) == 2

    discarded_by_host = {r["host_id"]: r for r in result.discarded}
    assert discarded_by_host["h41"]["exclusion_labels"] == ("missing_t_compile",)
    assert discarded_by_host["h42"]["exclusion_labels"] == (
        DiscardReason.PROCESS_EXCEEDS_TOTAL.value,
    )


def test_partition_t_fast_preset_keeps_only_the_dispatch_enabled_row():
    result = partition(_campaign(), required=REQUIRED_FOR_T_FAST)
    assert len(result.publishable) == 1
    assert result.publishable[0]["host_id"] == "h7"
    assert len(result.discarded) == 10
    assert len(result.failed) == 1


def test_partition_t_fast_preset_also_excludes_an_inconsistent_row_with_a_valid_t_fast_seconds():
    """Same ruling as the t_weights case above, applied to REQUIRED_FOR_T_FAST:
    t_fast_seconds is computed independently of the T_total/T_process check
    too, so a clock-inconsistent run can still carry a perfectly plausible
    t_fast_seconds -- and it must still be discarded. `_CAMPAIGN` has no row
    expressing "dispatch-enabled AND inconsistent" at once (every dispatch-
    enabled row there, h7, happens to be consistent), so this is its own
    small, dedicated fixture built specifically to exercise the interaction
    -- a fixture of all-consistent-or-all-dispatchless rows could not."""
    consistent = derive(
        _record("A", "r-fast-ok", "h20", 20, marks=_A5_MARKS, warmup=_A5_WARMUP, t_result=203.0)
    )
    inconsistent = derive(
        _record("A", "r-fast-bad", "h21", 21, marks=_A5_MARKS, warmup=_A5_WARMUP, t_result=100.0)
    )
    assert consistent["consistent"] is True
    assert consistent["t_fast_seconds"] is not None
    assert inconsistent["consistent"] is False
    assert inconsistent["t_fast_seconds"] is not None  # valid despite the flag

    result = partition([consistent, inconsistent], required=REQUIRED_FOR_T_FAST)
    assert result.publishable == [consistent]
    assert len(result.discarded) == 1
    assert result.discarded[0]["host_id"] == "h21"
    assert DiscardReason.PROCESS_EXCEEDS_TOTAL.value in result.discarded[0]["exclusion_labels"]


def test_partition_different_presets_disagree_on_the_same_row():
    """The row demonstrating that "publishable" cannot be one fixed predicate:
    h5 (the merged run) is publishable under REQUIRED_FOR_T_TOTAL (it is
    clock-consistent) but discarded under REQUIRED_FOR_T_WEIGHTS (its
    t_weights is None). A single hardcoded notion of publishable could not
    represent this row correctly under both callers at once."""
    rows = _campaign()
    by_total = partition(rows, required=REQUIRED_FOR_T_TOTAL)
    by_weights = partition(rows, required=REQUIRED_FOR_T_WEIGHTS)
    assert any(r["host_id"] == "h5" for r in by_total.publishable)
    assert any(r["host_id"] == "h5" for r in by_weights.discarded)


def test_discarded_rows_carry_their_exclusion_reason():
    result = partition(_campaign(), required=REQUIRED_FOR_T_TOTAL)
    (row,) = result.discarded
    assert row["exclusion_reason"] == DiscardReason.PROCESS_EXCEEDS_TOTAL.value
    assert row["exclusion_labels"] == (DiscardReason.PROCESS_EXCEEDS_TOTAL.value,)

    # REQUIRED_FOR_T_WEIGHTS now discards for two distinct reasons (the
    # consistency ruling above) -- look up each row by its own reason rather
    # than assuming there is exactly one discarded row.
    result = partition(_campaign(), required=REQUIRED_FOR_T_WEIGHTS)
    by_host = {r["host_id"]: r for r in result.discarded}
    assert by_host["h5"]["exclusion_reason"] == "missing_t_weights"
    assert by_host["h5"]["exclusion_labels"] == ("missing_t_weights",)
    assert by_host["h4"]["exclusion_reason"] == DiscardReason.PROCESS_EXCEEDS_TOTAL.value
    assert by_host["h4"]["exclusion_labels"] == (DiscardReason.PROCESS_EXCEEDS_TOTAL.value,)


def test_partition_does_not_mutate_the_original_rows():
    rows = _campaign()
    original_keys = [set(r.keys()) for r in rows]
    partition(rows, required=REQUIRED_FOR_T_TOTAL)
    assert [set(r.keys()) for r in rows] == original_keys


# ---------------------------------------------------------------------------
# failure_rate_by_arm / discard_table -- separable, per plan's requirement
# ---------------------------------------------------------------------------


def test_failure_rate_by_arm_counts_only_the_failed_run():
    rates = failure_rate_by_arm(_campaign())
    assert rates["A"] == {"total": 5, "failed": 0, "by_class": {}, "rate": 0.0}
    assert rates["B"] == {"total": 3, "failed": 1, "by_class": {"oom": 1}, "rate": pytest.approx(1 / 3)}
    assert rates["C"] == {"total": 4, "failed": 0, "by_class": {}, "rate": 0.0}


def test_discard_table_counts_only_the_discarded_row_for_the_given_preset():
    result = partition(_campaign(), required=REQUIRED_FOR_T_TOTAL)
    table = discard_table(result.discarded)
    assert table == {
        "C": {"total": 1, "by_reason": {DiscardReason.PROCESS_EXCEEDS_TOTAL.value: 1}}
    }


def test_failure_rate_and_discard_rate_are_nonzero_on_different_arms_and_cannot_be_confused():
    """The fixture the plan calls for explicitly: both rates non-zero, and
    different, so a bug that conflates them (the `not consistent` conflation
    B4 names) cannot pass by coincidence. Arm B has the only failure; arm C
    has the only discard (under the T_total preset) -- disjoint arms, and
    arm B's own row never appears in discard_table's output at all."""
    rates = failure_rate_by_arm(_campaign())
    result = partition(_campaign(), required=REQUIRED_FOR_T_TOTAL)
    table = discard_table(result.discarded)

    assert rates["B"]["failed"] > 0
    assert table.get("C", {}).get("total", 0) > 0
    assert rates["B"]["failed"] != table.get("C", {}).get("total", 0) or "B" not in table
    assert "B" not in table  # arm B's failure never shows up as a discard
    assert rates.get("C", {}).get("failed", 0) == 0  # arm C's discard never shows up as a failure


# ---------------------------------------------------------------------------
# within_host_triples -- a failed run must not enter the paired analysis
# ---------------------------------------------------------------------------


def test_within_host_triples_excludes_the_triple_with_a_failed_run():
    """Before the B4 fix, triple 2 (h3: A ok, B failed, C ok) looked complete
    to within_host_triples -- same triple_index, same host_id, and a failed
    row still carries `arm`. Only triples 0 and 1 must survive."""
    kept = within_host_triples(_campaign())
    assert [t[0]["triple_index"] for t in kept] == [0, 1]
    assert all(row["ok"] is True for triple in kept for row in triple)


# ---------------------------------------------------------------------------
# figures.py / stats.py refuse to crash on an unfiltered row
# ---------------------------------------------------------------------------


def test_waterfall_raises_not_publishable_on_an_unfiltered_failed_row():
    from coldstart.analysis.figures import waterfall

    with pytest.raises(NotPublishableError):
        waterfall(_campaign(), "/dev/null")


def test_bootstrap_median_diff_raises_a_clear_error_on_an_unfiltered_merged_row():
    """The exact bug scenario the plan names as worst-case: pooling
    `r["t_weights"]` for arm A, unfiltered, includes the merged run's None
    and used to die with a bare TypeError from inside math.isfinite."""
    rows = _campaign()
    arm_a = [r["t_weights"] for r in rows if r["arm"] == "A" and r["ok"]]
    assert None in arm_a  # the merged row's contribution -- fixture sanity
    with pytest.raises(ValueError, match="None"):
        bootstrap_median_diff(arm_a, [1.0] * 25, iterations=50)


# ---------------------------------------------------------------------------
# the Task 19 pooling pattern, at a scale where the bootstrap actually runs,
# on a campaign containing a merged run
# ---------------------------------------------------------------------------


def _clean_record(arm: str, run_id: str, host_id: str, triple_index: int) -> RunRecord:
    return _record(arm, run_id, host_id, triple_index)


def test_task19_pooling_pattern_works_through_the_gate_on_a_campaign_with_a_merged_run():
    """Reproduces Task 19's own end-to-end snippet (derive every row, pool
    t_weights per arm, bootstrap the median difference) at a large enough N
    for bootstrap_median_diff's MIN_BOOTSTRAP_SAMPLES floor to actually run,
    on a campaign that includes one engine-merged run -- the exact input that
    used to kill the snippet verbatim."""
    records = [_clean_record("A", f"r-a{i}", f"ha{i}", 100 + i) for i in range(21)]
    records.append(
        _record(
            "A",
            "r-a-merged",
            "ha-merged",
            200,
            marks=[m for m in _SIMPLE_MARKS if m["stage"] != "S3_load_done"],
        )
    )
    records += [_clean_record("B", f"r-b{i}", f"hb{i}", 300 + i) for i in range(21)]

    rows = [derive(r) for r in records]
    result = partition(rows, required=REQUIRED_FOR_T_WEIGHTS)

    by_a = [r["t_weights"] for r in result.publishable if r["arm"] == "A"]
    by_b = [r["t_weights"] for r in result.publishable if r["arm"] == "B"]
    assert len(by_a) == 21  # the merged run's None was excluded, not pooled
    assert len(by_b) == 21
    assert None not in by_a

    out = bootstrap_median_diff(by_a, by_b, iterations=200, seed=1)
    assert out["point"] == pytest.approx(0.0)  # both arms share the same t_weights fixture value
