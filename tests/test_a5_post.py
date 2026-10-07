"""Artifact 5's post against its data and its own contract.

- The numbers block is exactly what the analysis generates.
- Every figure it links exists, tracked, beside the post.
- The sections the approved design requires are present, in order.
- Top-up instances, if any, are disclosed.
- No mean appears: the tool's summary statistics never reach the post."""

import json
import re
from pathlib import Path

from multilora.numbers import block_in, numbers_block

REPO = Path(__file__).resolve().parents[1]
POST = REPO / "docs" / "post-a5.md"
ANALYSIS = REPO / "data" / "a5" / "analysis.json"
FIGURES = ("throughput_ttft", "kv_capacity", "equivalence", "cost_per_tenant")
SECTIONS = (
    "## Headline",
    "## The main chart",
    "## Registered is not active",
    "## Tenants per GPU, and what one costs",
    "## Synthetic adapters, and how I know they are valid here",
    "## Method",
    "## Adapters versus swapping models",
    "## Memory is a capacity question",
    "## Limits",
    "## Reproduce it",
    "## Next",
)


def _post() -> str:
    return POST.read_text()


def test_the_numbers_block_is_current():
    assert block_in(_post()) == numbers_block(json.loads(ANALYSIS.read_text()))


def test_every_figure_is_linked_and_exists():
    links = set(re.findall(r"\]\((figures/a5/[\w-]+\.png)\)", _post()))
    assert {f"figures/a5/{f}.png" for f in FIGURES} <= links
    for link in links:
        assert (POST.parent / link).is_file(), link


def test_the_required_sections_appear_in_order():
    text = _post()
    positions = [text.find(h + "\n") for h in SECTIONS]
    assert -1 not in positions, [h for h, p in zip(SECTIONS, positions) if p == -1]
    assert positions == sorted(positions)


def test_top_up_instances_are_disclosed():
    if json.loads(ANALYSIS.read_text()).get("topup_instances"):
        assert "top-up" in _post().lower()


def test_no_mean_is_published():
    """`peak-to-average` is a pre-registered parameter's name, not a statistic.
    Little's law, which the memory bound uses, is written as time in system."""
    text = re.sub(r"peak-to-average", "", _post(), flags=re.IGNORECASE)
    assert not re.search(r"\bmean\b|\baverage\b", text, re.IGNORECASE)
