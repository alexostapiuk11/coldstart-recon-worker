"""Every published number must come back out of the stored JSONL.

Skipped until the campaign exists, so the suite stays green before Task 9.
"""

import json
from pathlib import Path

import pytest

from coldstart.analysis.metrics import derive
from coldstart.analysis.pipeline import REQUIRED_FOR_T_TOTAL, partition
from coldstart.analysis.stats import bootstrap_median_diff
from coldstart.store import JsonlStore

STORE = Path("data/campaign.jsonl")
ANALYSIS = Path("data/analysis.json")

pytestmark = pytest.mark.skipif(
    not (STORE.exists() and ANALYSIS.exists()),
    reason="campaign data not present yet",
)


def _rows():
    return [derive(r) for r in JsonlStore(STORE).read_all()]


def test_every_record_reads_back_at_the_current_schema():
    assert len(JsonlStore(STORE).read_all()) > 0


def test_contrast_reproduces_bit_for_bit_from_the_store():
    """Same store, same seed, same iterations -> same interval. If this drifts,
    the published number cannot be re-derived by a reader.

    scripts/analyse.py withholds this contrast -- publishing a "withheld: ..."
    string instead of a bootstrap dict -- when arm B or arm C has no
    publishable t_compile rows (see `_bootstrap_or_withhold`). There is then
    no numeric interval to reproduce bit-for-bit, so this test instead checks
    that the withhold condition still holds against the current store: the
    published "withheld" claim would itself be stale if the store now has
    rows for both arms.
    """
    published = json.loads(ANALYSIS.read_text())["contrast_B_to_C_t_compile"]
    pub = partition(_rows(), required=REQUIRED_FOR_T_TOTAL).publishable
    by = {a: [r["t_compile"] for r in pub if r["arm"] == a] for a in "ABC"}
    if isinstance(published, str):
        assert published.startswith("withheld:")
        assert not by["B"] or not by["C"], (
            "analysis.json withholds contrast_B_to_C_t_compile, but the store "
            "now has publishable t_compile rows for both B and C"
        )
        return
    again = bootstrap_median_diff(by["B"], by["C"], iterations=10_000, seed=2)
    assert again == pytest.approx(published, rel=1e-12)


def test_no_published_row_is_missing_a_headline_field():
    for row in partition(_rows(), required=REQUIRED_FOR_T_TOTAL).publishable:
        for field in ("t_total", "t_s4_bracket", "t_compile", "kv_capacity_tokens"):
            assert row[field] is not None, f"{field} missing on {row['arm']}/{row['host_id']}"


def test_failure_and_discard_counts_add_up():
    rows = _rows()
    p = partition(rows, required=REQUIRED_FOR_T_TOTAL)
    assert len(p.publishable) + len(p.discarded) + len(p.failed) == len(rows)
