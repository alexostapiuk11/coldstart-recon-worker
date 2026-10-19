"""A `matrix` chart as an HTML table: rows by columns of short text cells.

Each cell has a status and a tone. The tone fills the cell (study.page.MATRIX_CSS mixes a
theme token into the card colour) and adds a glyph, the status sets its texture: solid
for observed, hatched for predicted, a dotted outline for pending. Neither is colour
alone: every cell also carries its status and tone in words, read by screen readers and
shown on phones, where the table becomes one card per row listing "column: text".
"""

from __future__ import annotations

from study.schema import MATRIX_STATUSES, MATRIX_TONES
from study.svg import _note
from study.text import esc

STATUS_WORDS = {"observed": "observed", "predicted": "predicted", "pending": "pending",
                "none": "no entry", "n/a": "not applicable"}
TONE_WORDS = {"bad": "bad", "warn": "watch", "ok": "good", "neutral": ""}
GLYPHS = {"bad": "✕", "warn": "!", "ok": "✓"}
BLANK = {"none": "—", "n/a": "n/a"}


def words(chart: dict) -> tuple[dict, dict]:
    """(status -> word, tone -> word): the defaults, overridden by the chart's legend."""
    status, tone = dict(STATUS_WORDS), dict(TONE_WORDS)
    for e in chart.get("legend", []):
        if "status" in e:
            status[e["status"]] = e["label"]
        else:
            tone[e["tone"]] = e["label"]
    return status, tone


def cell_words(cell: dict, status: dict, tone: dict) -> str:
    """'predicted, bad': the status's word, then the tone's when it has one."""
    t = tone.get(cell.get("tone", "neutral"), "")
    return ", ".join(w for w in (status[cell["status"]], t) if w)


def cell_text(cell: dict) -> str:
    return cell["text"] if cell["text"].strip() else BLANK.get(cell["status"], "")


def _head(h: dict) -> str:
    sub = f"<small>{esc(h['sub'])}</small>" if h.get("sub") else ""
    return f"{esc(h['label'])}{sub}"


def matrix_html(chart: dict) -> str:
    status, tone = words(chart)
    rows, cols = chart["rows"], chart["cols"]
    unit = chart["unit"]
    aria = (f"Matrix ({unit}): " if unit else "Matrix: ") + (
        f"{len(rows)} rows by {len(cols)} columns")
    head = (f'<th scope="col" class="mxcorner"><span class="mxunit">{esc(unit)}</span></th>'
            + "".join(f'<th scope="col">{_head(c)}</th>' for c in cols))
    body = []
    for r, cells in zip(rows, chart["cells"]):
        tds = []
        for c, cell in zip(cols, cells):
            t = cell.get("tone", "neutral")
            st = cell["status"].replace("/", "")
            glyph = (f'<span class="mxg" aria-hidden="true">{GLYPHS[t]}</span>'
                     if t in GLYPHS else "")
            note = f'<small class="mxnote">{esc(cell["note"])}</small>' if cell.get("note") else ""
            tds.append(f'<td class="mxc st-{st} t-{t}" data-col="{esc(c["label"])}">'
                       f'<span class="mxt">{glyph}{esc(cell_text(cell))}</span>{note}'
                       f'<span class="mxs">{esc(cell_words(cell, status, tone))}</span></td>')
        body.append(f'<tr><th scope="row">{_head(r)}</th>{"".join(tds)}</tr>')
    table = (f'<div class="mxwrap"><table class="mx" aria-label="{esc(aria)}">'
             f'<thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')

    used = [c for row in chart["cells"] for c in row]
    items = [f'<li><span class="mxsw st-{s.replace("/", "")}"></span>{esc(status[s])}</li>'
             for s in MATRIX_STATUSES if any(c["status"] == s for c in used)]
    items += [f'<li><span class="mxsw mxswt t-{t}">{GLYPHS[t]}</span>{esc(tone[t])}</li>'
              for t in MATRIX_TONES if t in GLYPHS and any(c.get("tone") == t for c in used)]
    return table + f'<ul class="legend mxleg">{"".join(items)}</ul>' + _note(chart)
