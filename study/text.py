"""Escaping and the two bits of inline markup the content may use."""

import html
import re


def esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def inline(s: str) -> str:
    """Escape, then turn **bold** and `code` into tags. Nothing else is interpreted."""
    out = esc(s)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", out)
