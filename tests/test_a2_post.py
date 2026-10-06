"""docs/post-a2.md quotes every computed number, links every figure, and labels the
unvalidated simulator wherever its numbers appear."""

import json
import re
from pathlib import Path

import pytest

from autoscale.post_numbers_a2 import numbers

REPO = Path(__file__).resolve().parents[1]
POST = (REPO / "docs" / "post-a2.md").read_text()
A = json.loads((REPO / "data" / "a2" / "post-analysis.json").read_text())
FIGURES = ("attempts", "load_balancer", "host_speed", "simulator_answer", "service_curve")
PREREG = (REPO / "docs" / "experiment-a2.md").read_text()
# Amendments sit at two heading levels in the pre-registration: the 2026-09 ones are
# subsections (###) of the section they amend, the 2026-10 ones are sections (##).
# Rejected: matching "## " only, which skips the three earlier amendments.
AMENDMENT = re.compile(r"^#{2,3} Amendment, (\d{4}-\d{2}-\d{2}(?: \(\w+\))?)", re.MULTILINE)


def test_every_computed_number_is_quoted_verbatim():
    missing = [k for k, v in numbers(A).items() if v not in POST]
    assert not missing, missing


def test_the_header_has_the_permanent_slug_byline_and_repo_link():
    assert "Permanent slug: /experiments/autoscaling-signal-and-cold-start" in POST
    # The date is set at the pre-publish gate; until then the placeholder stands.
    assert re.search(r"^\*\*Oleksii Ostapiuk\*\* · (\d{4}-\d{2}-\d{2}|PUBLICATION-DATE) · ",
                     POST, re.MULTILINE)
    assert "github.com/alexostapiuk11/coldstart-recon-worker" in POST


def test_the_simulator_section_is_labelled_unvalidated():
    section = POST.split("## What the unvalidated simulator says", 1)[1].split("\n## ", 1)[0]
    assert "failed" in section and "not a measurement" in section
    assert "exploratory" in section


def test_the_amendment_pattern_finds_every_amendment_heading():
    # A heading the pattern misses would be a missing amendment that passes the test below.
    headings = re.findall(r"^#+ Amendment, ", PREREG, re.MULTILINE)
    assert len(AMENDMENT.findall(PREREG)) == len(headings) >= 9


def test_every_amendment_is_listed_in_reproducing_this():
    dates = AMENDMENT.findall(PREREG)
    repro = POST.split("## Reproducing this", 1)[1]
    assert all(d in repro for d in dates), dates
    assert "Analysis note, 2026-10-05" in repro


@pytest.mark.parametrize("name", FIGURES)
def test_the_post_links_the_published_figure(name):
    assert f"(figures/a2/{name}.png)" in POST


def test_the_sections_are_in_order():
    heads = re.findall(r"^## (.+)$", POST, re.MULTILINE)
    want = ["The question", "What was measured and what was simulated",
            "The test the simulator had to pass",
            "Attempt one: the engine was faster than the curve",
            "Attempt two: calibrated, and wrong the other way",
            "What RunPod's load balancer does", "What the unvalidated simulator says",
            "The service curve", "What it costs", "Limits", "Reproducing this", "Next"]
    assert heads == want
