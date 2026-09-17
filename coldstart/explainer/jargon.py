"""The jargon contract, as a check rather than an intention.

"Avoid jargon" cannot be tested. "Every listed term that appears on the page
appears with its definition" can be, and that is the version that survives
contact with a build.
"""

import json
from pathlib import Path

TERMS: dict[str, str] = json.loads(
    (Path(__file__).resolve().parents[2] / "explainer" / "terms.json").read_text()
)


_TYPOGRAPHIC = {
    "\u2019": "'",
    "\u2018": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2014": "-",
    "\u2013": "-",
    "\u00a0": " ",
}


def _normalize(text: str) -> str:
    """Fold typographic punctuation to ASCII before matching.

    The definitions are authored with straight quotes and hyphens; the rendered
    page uses curly quotes and em dashes. Without this, a definition that IS
    present fails the check purely on punctuation, and the build stops for a
    reason that has nothing to do with jargon. Fails loudly rather than
    silently, but it would still waste the author's time on every edit.
    """
    for fancy, plain in _TYPOGRAPHIC.items():
        text = text.replace(fancy, plain)
    return " ".join(text.lower().split())


def undefined_terms(html: str) -> list[str]:
    """Listed terms that appear in `html` without their definition nearby.

    A term counts as defined only if its *full* definition text is present,
    not merely a prefix of it. A fixed-length prefix (e.g. the first 40
    characters) would let a page pass with the opening words of a definition
    followed by anything -- including a wrong or truncated ending -- since
    only that prefix is ever checked. Requiring the whole definition string
    closes that gap while staying a plain substring check: no natural-language
    parsing, just "is this exact text present."
    """
    haystack = html.lower()
    haystack = _normalize(html)
    missing = []
    for term, definition in TERMS.items():
        if term.lower() not in haystack:
            continue
        if definition.lower() not in haystack:
            missing.append(term)
    return missing
