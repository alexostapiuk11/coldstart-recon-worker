"""The A4 pre-publish check refuses what A2's does, plus A4's DRAFT line."""
import json

from scripts.a4_prepublish_check import problems

GOOD_ANALYSIS = {"spend": {"total_usd": 25.2311}}


def test_ok_when_dated_and_spent():
    assert problems("# t\n\n**Oleksii Ostapiuk** · 2026-11-20 · `/x`\n", GOOD_ANALYSIS) == []


def test_refuses_publication_date_placeholder():
    found = problems("**Oleksii Ostapiuk** · PUBLICATION-DATE · `/x`\n", GOOD_ANALYSIS)
    assert any("PUBLICATION-DATE" in p for p in found)


def test_refuses_draft_line():
    found = problems("DRAFT for the owner's review\n\n**A** · 2026-11-20 · `/x`\n", GOOD_ANALYSIS)
    assert any("DRAFT" in p for p in found)


def test_refuses_null_spend():
    found = problems("**A** · 2026-11-20 · `/x`\n", {"spend": None})
    assert any("spend" in p for p in found)


def test_skips_html_comments():
    text = "<!--\nPUBLICATION-DATE is a placeholder.\nDRAFT for the owner's review.\n-->\n**A** · 2026-11-20 · `/x`\n"
    assert problems(text, GOOD_ANALYSIS) == []
