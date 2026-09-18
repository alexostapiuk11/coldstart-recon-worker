"""Every number on the page resolves from committed data.

Not "every number matches analysis.json" -- that was unsatisfiable, because
analysis.json carries no per-phase medians, no paired B->C contrast, no
first-touch run and no single-sample intervals. The key list is the contract;
this asserts it holds.
"""

import json
from pathlib import Path

import pytest

from coldstart.explainer.numbers import KEYS, resolve

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("key", sorted(KEYS))
def test_every_key_resolves(key):
    value = resolve(key, repo=REPO)
    assert value is not None, f"{key} resolved to None"


def test_headline_numbers_match_the_published_analysis():
    analysis = json.loads((REPO / "data" / "analysis.json").read_text())
    assert resolve("median_t_total_C", repo=REPO) == analysis["distributions"]["C"]["p50"]
    d = resolve("difference_of_contrasts", repo=REPO)
    assert (d["lo"], d["hi"]) == (
        analysis["difference_of_contrasts_t_total"]["lo"],
        analysis["difference_of_contrasts_t_total"]["hi"],
    )


def test_the_single_sample_interval_is_the_gated_n99_sample():
    """The statistics module is pinned to the repeat-host sample, not the raw
    n=100 that still contains the 2266s first-touch run."""
    ci = resolve("arm_a_ci_n99", repo=REPO)
    assert ci["n"] == 99
    assert round(ci["lo"], 2) == 80.91
    assert round(ci["hi"], 2) == 85.88


def test_unknown_key_raises():
    with pytest.raises(KeyError):
        resolve("not_a_key", repo=REPO)
