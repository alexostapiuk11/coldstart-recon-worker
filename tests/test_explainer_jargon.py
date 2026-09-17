from pathlib import Path

from coldstart.explainer.jargon import TERMS, undefined_terms

REPO = Path(__file__).resolve().parents[1]


def test_a_term_used_without_its_definition_is_reported():
    page = "<p>The KV cache is sized at startup.</p>"
    assert "KV cache" in undefined_terms(page)


def test_a_term_used_with_its_definition_passes():
    page = f"<p>The KV cache — {TERMS['KV cache']} — is sized at startup.</p>"
    assert "KV cache" not in undefined_terms(page)


def test_a_page_using_no_listed_terms_reports_nothing():
    assert undefined_terms("<p>Nothing technical here.</p>") == []


def test_a_term_appearing_only_inside_a_code_excerpt_is_still_reported():
    """The page embeds real code (see excerpts.py) alongside prose. A term
    that only shows up inside a `<pre><code>` block -- e.g. because a
    snippet calls `torch.compile(...)` -- is still jargon on the page and
    still needs its plain-language definition somewhere, same as if it had
    appeared in a sentence."""
    page = "<pre><code>model = torch.compile(model)</code></pre>"
    assert "torch.compile" in undefined_terms(page)
