"""Artifact 4's post quotes its numbers from the committed analysis, follows
the structure August §10 fixed, and carries the explanations it requires.

Every headline number is rendered by `placement.post_numbers` and must appear
verbatim: a number typed by hand drifts the first time the data is
re-analysed. The section headings are August §10's post structure."""

import json
from pathlib import Path

import pytest

from placement.post_numbers import numbers

REPO = Path(__file__).resolve().parents[1]
POST = (REPO / "docs" / "post-a4.md").read_text()
ANALYSIS = json.loads((REPO / "data" / "a4" / "analysis.json").read_text())
HEADINGS = (
    "## The crossover",
    "## Why the naive answer is wrong",
    "## The three primitives, measured",
    "## Method",
    "## Where the boundary moves",
    "## The excluded option",
    "## Limits",
    "## Reproduce it",
    "## Next",
)
# August §10's required explanations, and the amendment's additions: each must
# be argued in the post, so each has a phrase the argument cannot avoid.
REQUIRED = (
    "skips",                # why a swap is cheaper than a cold start, and what it skips
    "interpreter",          # a process-level swap re-pays interpreter startup (amendment §5)
    "KV",                   # why a shrunken KV budget hurts more than proportionally
    "aggregate p99",        # why the aggregate is the wrong SLO for a multi-tenant fleet
    "adapter",              # the excluded fourth option and its precondition
    "validated",            # the validated operating point, and extrapolation beyond it
    "pre-registration",     # the link to docs/experiment-a4.md
)


@pytest.mark.parametrize("key, value", sorted(numbers(ANALYSIS).items()))
def test_every_headline_number_is_quoted_verbatim(key, value):
    assert value in POST, f"{key}: the post does not say {value!r}"


@pytest.mark.parametrize("heading", HEADINGS)
def test_the_post_follows_the_fixed_structure(heading):
    assert f"\n{heading}" in POST


def test_the_headings_are_in_order():
    positions = [POST.index(f"\n{h}") for h in HEADINGS]
    assert positions == sorted(positions)


@pytest.mark.parametrize("phrase", REQUIRED)
def test_each_required_explanation_is_there(phrase):
    assert phrase in POST


def test_the_post_has_its_permanent_slug_and_links_the_pre_registration():
    assert "Permanent slug: /experiments/" in POST
    assert "experiment-a4.md" in POST
