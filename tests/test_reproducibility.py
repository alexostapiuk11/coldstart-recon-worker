"""Every published number must come back out of the stored JSONL.

Skipped until the campaign exists, so the suite stays green before Task 9.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coldstart.analysis.metrics import derive
from coldstart.analysis.pipeline import REQUIRED_FOR_T_COMPILE, REQUIRED_FOR_T_TOTAL, partition
from coldstart.analysis.stats import MIN_BOOTSTRAP_SAMPLES, bootstrap_median_diff
from coldstart.store import JsonlStore
from scripts.analyse import ITERATIONS

STORE = Path("data/campaign.jsonl")
ANALYSIS = Path("data/analysis.json")

pytestmark = pytest.mark.skipif(
    not (STORE.exists() and ANALYSIS.exists()),
    reason="campaign data not present yet",
)

# Each row mirrors one bootstrap_median_diff(...) call site in
# scripts/analyse.py's _full_analysis(): the analysis key it writes, the
# `required` preset that built its per-arm samples there, the field pooled,
# the two arms contrasted (in the order analyse.py subtracts them), and the
# seed literal that call site passes. ITERATIONS is imported from
# scripts.analyse so it can never silently drift from analyse.py's own
# constant; the per-contrast seeds are NOT importable -- they are inline
# literals at each call site, and analyse.py belongs to another implementer
# right now -- so they are duplicated here by hand. That duplication cannot
# fail silently (a changed seed makes the reproduced interval mismatch and
# this test fails loudly); it just means two places need updating in
# lockstep if a seed is ever deliberately changed.
CONTRASTS = [
    # scripts/analyse.py: out["contrast_B_to_C_t_compile"], seed=2
    pytest.param(
        "contrast_B_to_C_t_compile",
        REQUIRED_FOR_T_COMPILE,
        "t_compile",
        "B",
        "C",
        2,
        id="B_to_C_t_compile",
    ),
    # scripts/analyse.py: out["contrast_A_to_B_t_total"], seed=5
    pytest.param(
        "contrast_A_to_B_t_total", REQUIRED_FOR_T_TOTAL, "t_total", "A", "B", 5, id="A_to_B_t_total"
    ),
    # scripts/analyse.py: out["contrast_B_to_C_t_total"], seed=6
    pytest.param(
        "contrast_B_to_C_t_total", REQUIRED_FOR_T_TOTAL, "t_total", "B", "C", 6, id="B_to_C_t_total"
    ),
]


def _rows():
    return [derive(r) for r in JsonlStore(STORE).read_all()]


def test_every_record_reads_back_at_the_current_schema():
    """Not just non-empty: JsonlStore.read_all()/RunRecord.from_dict already
    raise if a stored record's schema_version disagrees with this build's
    (coldstart/schema.py), so getting past that call at all already proves
    the versions agree. This also pins that derive() still recognises every
    row well enough to name it by arm and host -- the minimum a
    reproducibility check owes its own name."""
    records = JsonlStore(STORE).read_all()
    assert records, "store is empty"
    for row in _rows():
        assert row["arm"] in ("A", "B", "C")
        assert row["host_id"]


@pytest.mark.parametrize("key, required, field, arm_a, arm_b, seed", CONTRASTS)
def test_contrast_reproduces_bit_for_bit_from_the_store(key, required, field, arm_a, arm_b, seed):
    """Same store, same seed, same iterations -> same interval. If this
    drifts, the published number cannot be re-derived by a reader.

    Covers three of the six contrasts scripts/analyse.py publishes: B->C
    t_compile plus both t_total contrasts. t_total is gated only by the
    universal REQUIRED_FOR_T_TOTAL consistency floor and pools the broadest
    publishable set of any contrast, so it is implausible for every numeric
    check in this module to go inert (withheld) at once the way relying on
    t_compile alone would. Per-arm distributions were considered as a second
    fallback and rejected: percentiles()'s floor (MIN_SAMPLES["p95"] == 80)
    is stricter than the bootstrap's own MIN_BOOTSTRAP_SAMPLES == 20, so a
    distribution is MORE likely to be withheld than a contrast, not a safer
    backstop.

    scripts/analyse.py withholds a contrast -- publishing the uniform
    `{"withheld": true, "reason": ...}` envelope instead of a bootstrap
    result -- when either arm has fewer publishable rows than
    MIN_BOOTSTRAP_SAMPLES (see `_floor_or_withhold`). There is then no
    numeric interval to reproduce bit-for-bit, so this test instead checks
    that the withhold condition still holds against the current store, and
    that the reason names exactly the arm(s) that are actually short -- not
    merely that some arm is short, which would still pass if the published
    reason named a different arm than the one the store now shows short.
    `_floor_or_withhold` builds its reason from exactly the short labels, so
    membership can be asserted directly without rebuilding the reason string
    (that would just duplicate its formatting logic and drift in lockstep).

    `t_compile` is gated by REQUIRED_FOR_T_COMPILE, not REQUIRED_FOR_T_TOTAL:
    it has its own nullity condition (an undelineated S4b), independent of
    clock consistency, exactly like `t_weights` and REQUIRED_FOR_T_WEIGHTS --
    so this test pools it the same way scripts/analyse.py's `by_c` does, via
    the `required` preset threaded in through CONTRASTS above, not through
    the plain T_TOTAL gate the t_total contrasts use.
    """
    published = json.loads(ANALYSIS.read_text())[key]
    pub = partition(_rows(), required=required).publishable
    by = {a: [r[field] for r in pub if r["arm"] == a] for a in "ABC"}
    a_short = len(by[arm_a]) < MIN_BOOTSTRAP_SAMPLES
    b_short = len(by[arm_b]) < MIN_BOOTSTRAP_SAMPLES
    if published["withheld"]:
        assert a_short or b_short, (
            f"analysis.json withholds {key}, but the store now has enough "
            f"publishable {field} rows for both {arm_a} and {arm_b}"
        )
        assert (f"arm {arm_a}" in published["reason"]) == a_short
        assert (f"arm {arm_b}" in published["reason"]) == b_short
        return
    again = bootstrap_median_diff(by[arm_a], by[arm_b], iterations=ITERATIONS, seed=seed)
    published_interval = {k: v for k, v in published.items() if k != "withheld"}
    assert again == pytest.approx(published_interval, rel=1e-12)


def test_t_total_is_never_missing_on_a_t_total_publishable_row():
    """REQUIRED_FOR_T_TOTAL guarantees only `consistent` -- but `t_total`
    itself is None exactly when `consistent` is False (metrics.derive()), so
    this is a genuine invariant of that preset, not an accident of today's
    data."""
    for row in partition(_rows(), required=REQUIRED_FOR_T_TOTAL).publishable:
        assert row["t_total"] is not None, f"t_total missing on {row['arm']}/{row['host_id']}"


def test_t_compile_is_never_missing_on_a_t_compile_publishable_row():
    """Mirrors the t_total check above, under the preset that actually
    governs t_compile. REQUIRED_FOR_T_TOTAL does NOT guarantee this field --
    a consistent run with an undelineated S4b is a real, expected shape
    (tests/test_pipeline.py pins exactly this row), so checking it under
    T_TOTAL would turn one legitimate merged-phase run anywhere in the
    campaign into a suite-wide failure for a normal data condition, not a
    reproducibility break -- this was the Critical finding. REQUIRED_FOR_T_
    COMPILE is the preset that already excludes that row from `publishable`,
    so nothing reaching this loop can be None."""
    for row in partition(_rows(), required=REQUIRED_FOR_T_COMPILE).publishable:
        assert row["t_compile"] is not None, f"t_compile missing on {row['arm']}/{row['host_id']}"


def test_s4_bracket_and_kv_capacity_are_populated_on_most_publishable_rows():
    """`t_s4_bracket` and `kv_capacity_tokens` have no dedicated
    REQUIRED_FOR_* preset (coldstart/analysis/pipeline.py) -- each has its
    own independent nullity condition (missing S4_start/S4_end marks; an
    engine that reports neither total tokens nor blocks*block_size) that is
    expected to fire occasionally without indicating anything is broken, so
    a hard non-None invariant here would fail the whole suite on one
    legitimately thin row -- the same mistake the Critical finding caught
    for `t_compile`. The probe now emits S4_start/S4_end on every run
    (worker/probe.py) and both fields feed genuinely published figures
    (kv_capacity_median; t_s4_bracket underlies the S4-decomposition
    figures), so on a healthy campaign both should be populated on the
    large majority of publishable rows. A population-ratio check catches a
    real regression -- the probe silently stops emitting a mark, or the
    parser silently stops finding it -- without failing on the handful of
    legitimately merged rows a hard per-row assertion would trip on.
    """
    pub = partition(_rows(), required=REQUIRED_FOR_T_TOTAL).publishable
    assert pub, "no publishable rows to check"
    for field in ("t_s4_bracket", "kv_capacity_tokens"):
        present = sum(1 for r in pub if r[field] is not None)
        ratio = present / len(pub)
        assert ratio >= 0.9, (
            f"{field} present on only {present}/{len(pub)} publishable rows "
            f"({ratio:.0%}) -- expected on the large majority of a healthy campaign"
        )


def test_failure_and_discard_counts_add_up():
    rows = _rows()
    p = partition(rows, required=REQUIRED_FOR_T_TOTAL)
    assert len(p.publishable) + len(p.discarded) + len(p.failed) == len(rows)
