"""Escaping, the bits of inline markup the content may use, and links between units."""

import copy
import html
import re

# [text](unit:concept) in content: a link to a concept card (#c-<concept>) on a unit's page.
UNIT_LINK = re.compile(r"\[([^\[\]]+)\]\(([A-Za-z0-9_-]+):([A-Za-z0-9_-]+)\)")
# resolve_links(..., "page") turns each into \x01text\x02url\x03, which inline() renders as
# an <a> and esc() as its text. Content never carries these characters (schema rejects them),
# so only a link resolved here can become an <a>.
_RESOLVED = re.compile("\x01([^\x01\x02\x03]*)\x02([^\x01\x02\x03]*)\x03")
SENTINELS = "\x01\x02\x03"


def esc(s: object) -> str:
    return html.escape(_RESOLVED.sub(r"\1", str(s)), quote=True)


def _anchor(m: re.Match) -> str:
    text, url = m.group(1), m.group(2)
    if url.startswith("#"):
        return f'<a href="{url}">{text}</a>'
    return f'<a href="{url}" target="_blank" rel="noopener">{text}</a>'


# *italic*: single asterisks hugging their words (so "2 * 3" stays), not inside a word,
# and never part of a ** pair (bold is replaced first).
_ITALIC = re.compile(r"(?<![*\w])\*(?=[^\s*])([^*]*?[^\s*])\*(?![*\w])")


def inline(s: str) -> str:
    """Escape, then turn **bold**, *italic*, `code` and resolved unit links into tags.
    Nothing else is interpreted."""
    out = html.escape(str(s), quote=True)
    out = _RESOLVED.sub(_anchor, out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = _ITALIC.sub(r"<em>\1</em>", out)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", out)


def plural(n: int, word: str) -> str:
    """'1 step', '3 steps'."""
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def wrap(text: str, width: int) -> list[str]:
    """Greedy word wrap into lines of at most `width` characters (longer words stay whole)."""
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + ([cur] if cur else [])


def known_units(c: dict) -> set[str]:
    """Units a link may name: this unit, every unit with a published URL, every prereq."""
    return ({c.get("id")} | set(c.get("links") or {})
            | {p.get("unit") for p in c.get("prereqs") or [] if isinstance(p, dict)})


def unit_url(c: dict, unit: str) -> str:
    """Where another unit's page lives: its published URL, else its file next to this one."""
    return (c.get("links") or {}).get(unit) or f"../{unit}/page.html"


def unknown_link_units(s: str, known: set[str]) -> list[str]:
    return [m.group(2) for m in UNIT_LINK.finditer(s) if m.group(2) not in known]


def resolve_links(c: dict, mode: str, own_url: str | None = None) -> dict:
    """A copy of the unit with every [text](unit:concept) link resolved for `mode`:

    - "page": a marker inline() renders as <a href="<url>#c-<concept>"> (new tab for
      another unit; a plain anchor for this unit's own concepts, or, when the content is not
      on the unit's own page (the practice page), `own_url` + "#c-<concept>") and esc() as
      the text;
    - "brief": plain text, "text (P1: concept)", or just the text for this unit.

    Raises ContentError for a link to a unit the content does not know (see known_units).
    """
    from study.schema import ContentError  # schema imports this module

    known = known_units(c)

    def one(m):
        text, unit, concept = m.groups()
        if unit not in known:
            raise ContentError(f"link to unknown unit '{unit}' in {m.group(0)!r}; add it to "
                               "`links` or `prereqs`")
        own = unit == c.get("id")
        if mode == "brief":
            return text if own else f"{text} ({unit.upper()}: {concept})"
        url = f"{own_url or ''}#c-{concept}" if own else f"{unit_url(c, unit)}#c-{concept}"
        return f"\x01{text}\x02{url}\x03"

    def walk(node, key=None):
        if isinstance(node, str):
            return node if key in ("sources", "links") else UNIT_LINK.sub(one, node)
        if isinstance(node, dict):
            return {k: (v if k in ("sources", "links") else walk(v, k)) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, key) for v in node]
        return copy.deepcopy(node)

    return walk(c)
