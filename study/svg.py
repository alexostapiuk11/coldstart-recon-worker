"""Inline SVG for C4 views and charts. Pure functions from content dicts to HTML.

Diagrams are a grid: each node names a column and row, and edges are straight lines
clipped to the box borders. On phones the SVG is hidden by CSS and a text list of the
same nodes and edges is shown instead, because a 4-column diagram scaled to 375 px is
unreadable.
"""

from __future__ import annotations

from study.text import esc

W, H, GX, GY, PAD = 170, 72, 50, 44, 24
GAP = 2  # surface gap between stacked segments (dataviz mark spec)
CHAR = 6.2  # estimated width of one 11 px edge-label character
LABEL_CHARS = 18  # edge labels wrap at this many characters
CHART_CHAR = 8.5  # width allowance per chart-text character (phone CSS sets up to 15 px)


def _clip(cx, cy, tx, ty, hw, hh):
    """Where the ray from (cx, cy) toward (tx, ty) leaves a box of half sizes hw, hh."""
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    sx = hw / abs(dx) if dx else float("inf")
    sy = hh / abs(dy) if dy else float("inf")
    s = min(sx, sy)
    return cx + dx * s, cy + dy * s


def _wrap(text: str, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + ([cur] if cur else [])


def diagram_html(view: dict, uid: str) -> str:
    nodes = {n["id"]: n for n in view["nodes"]}
    cols = max(n["col"] for n in nodes.values()) + 1
    rows = max(n["row"] for n in nodes.values()) + 1
    edges = view.get("edges", [])
    # Widen the column gap so a label on a same-row edge fits between the two boxes.
    gx = max([GX] + [round(len(line) * CHAR) + 16 for e in edges
                     if nodes[e["from"]]["row"] == nodes[e["to"]]["row"]
                     for line in _wrap(e.get("label", ""), LABEL_CHARS)])
    width = PAD * 2 + cols * W + (cols - 1) * gx
    height = PAD * 2 + rows * H + (rows - 1) * GY

    def center(n):
        return PAD + n["col"] * (W + gx) + W / 2, PAD + n["row"] * (H + GY) + H / 2

    head = (f'<svg class="diagram" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{esc(view["title"])}" xmlns="http://www.w3.org/2000/svg">')
    marker = (f'<defs><marker id="arr-{esc(uid)}" viewBox="0 0 10 10" refX="9" refY="5" '
              'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
              '<path d="M0,0 L10,5 L0,10 z" class="arrow"/></marker></defs>')
    p = [head, marker]
    for e in edges:
        (ax, ay), (bx, by) = center(nodes[e["from"]]), center(nodes[e["to"]])
        x1, y1 = _clip(ax, ay, bx, by, W / 2 + 2, H / 2 + 2)
        x2, y2 = _clip(bx, by, ax, ay, W / 2 + 6, H / 2 + 6)
        p.append(f'<line class="edge" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" '
                 f'y2="{y2:.1f}" marker-end="url(#arr-{esc(uid)})"/>')
        lines = _wrap(e.get("label", ""), LABEL_CHARS)
        for i, line in enumerate(lines):
            y = (y1 + y2) / 2 - 5 - (len(lines) - 1 - i) * 13
            p.append(f'<text class="elabel" x="{(x1 + x2) / 2:.1f}" '
                     f'y="{y:.1f}" text-anchor="middle">{esc(line)}</text>')
    for n in nodes.values():
        cx, cy = center(n)
        kind = n.get("kind", "system")
        p.append(f'<g class="node k-{kind}"><rect x="{cx - W / 2:.1f}" y="{cy - H / 2:.1f}" '
                 f'width="{W}" height="{H}" rx="8"/>')
        sub = _wrap(n.get("sub", ""), 30)[:2]
        top = cy - (len(sub) * 7) - 2 if sub else cy
        p.append(f'<text class="nlabel" x="{cx:.1f}" y="{top + 5:.1f}" '
                 f'text-anchor="middle">{esc(n["label"])}</text>')
        for i, line in enumerate(sub):
            p.append(f'<text class="nsub" x="{cx:.1f}" y="{top + 22 + i * 14:.1f}" '
                     f'text-anchor="middle">{esc(line)}</text>')
        p.append("</g>")
    p.append("</svg>")

    text = ['<div class="diagram-text"><ul>']
    for n in nodes.values():
        sub = f" — {esc(n['sub'])}" if n.get("sub") else ""
        text.append(f'<li><strong>{esc(n["label"])}</strong>{sub}</li>')
    text.append("</ul><ol>")
    for e in edges:
        lab = f": {esc(e['label'])}" if e.get("label") else ""
        text.append(f'<li>{esc(nodes[e["from"]]["label"])} → '
                    f'{esc(nodes[e["to"]]["label"])}{lab}</li>')
    text.append("</ol></div>")
    return "".join(p) + "".join(text)


def _num(v: float) -> str:
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.1f}".rstrip("0").rstrip(".")


def chart_html(chart: dict, uid: str) -> str:
    """Horizontal bars. `stacked_bars` stacks named segments; `bars` is one bar per item."""
    unit = esc(chart["unit"])
    stacked = chart["type"] == "stacked_bars"
    if stacked:
        bars = [(b["label"], [(s["name"], s["value"]) for s in b["segments"]])
                for b in chart["bars"]]
    else:
        bars = [(i["label"], [(i["label"], i["value"])]) for i in chart["items"]]
    totals = [sum(v for _, v in segs) for _, segs in bars]
    names = list(dict.fromkeys(n for _, segs in bars for n, _ in segs))
    full, pitch = 340.0, 58
    scale = full / max(totals)
    height = len(bars) * pitch + 4
    # Leave room after the longest bar for the longest total label, so none is clipped.
    tail = max(len(f"{_num(t)} {chart['unit']}") for t in totals) * CHART_CHAR + 6
    width = round(full + 6 + tail)
    p = [(f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
          f'aria-label="{unit} by bar" xmlns="http://www.w3.org/2000/svg">')]
    for r, ((label, segs), total) in enumerate(zip(bars, totals)):
        y = r * pitch
        p.append(f'<text class="blabel" x="0" y="{y + 14}">{esc(label)}</text>')
        x = 0.0
        for name, v in segs:
            w = v * scale
            cls = names.index(name) % 8 if stacked else 0
            # A 2 px surface gap separates touching segments; a sliver keeps its width.
            drawn = w - GAP if w > 2 * GAP else w
            p.append(f'<rect class="seg s{cls}" x="{x:.1f}" y="{y + 20}" width="{drawn:.1f}" '
                     f'height="24" rx="2"><title>{esc(name)}: {_num(v)} {unit}</title></rect>')
            # A plain bar's value is its total, shown at the tip; label stacked segments only.
            if stacked and drawn >= len(_num(v)) * CHART_CHAR + 8:
                p.append(f'<text class="segtext s{cls}" x="{x + drawn / 2:.1f}" y="{y + 36}" '
                         f'text-anchor="middle">{_num(v)}</text>')
            x += w
        p.append(f'<text class="btotal" x="{x + 6:.1f}" y="{y + 36}">{_num(total)} {unit}</text>')
    p.append("</svg>")
    legend = ""
    if stacked:
        chips = "".join(f'<li><span class="chip s{i % 8}"></span>{esc(n)}</li>'
                        for i, n in enumerate(names))
        legend = f'<ul class="legend">{chips}</ul>'
    return "".join(p) + legend
