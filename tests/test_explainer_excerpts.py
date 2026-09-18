"""Code shown in the explainer must be the code that is running.

Sentinels rather than line ranges or function names because the
harness-extraction plan rewrites import paths and will move this code. A
sentinel that disappears fails loudly here; a stale line range fails silently
on the page.
"""

from pathlib import Path

import pytest

from coldstart.explainer.excerpts import SENTINELS, extract

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("slug", sorted(SENTINELS))
def test_every_sentinel_still_exists_and_yields_code(slug):
    text = extract(slug, repo=REPO)
    assert text.strip(), f"{slug} extracted empty"
    assert len(text.splitlines()) <= 30, (
        f"{slug} is {len(text.splitlines())} lines — too long to read on a page"
    )


def test_extract_raises_a_named_error_when_a_sentinel_is_gone(tmp_path):
    f = tmp_path / "coldstart" / "preflight.py"
    f.parent.mkdir(parents=True)
    f.write_text("x = 1\n")
    with pytest.raises(LookupError, match="explainer:preflight-refuses"):
        extract("preflight-refuses", repo=tmp_path)


def test_handler_excerpt_carries_its_comment():
    """In handler.py the comment IS the lesson; an excerpt of the bare call
    would teach nothing."""
    text = extract("handler-snapshot-before", repo=REPO)
    assert "#" in text
