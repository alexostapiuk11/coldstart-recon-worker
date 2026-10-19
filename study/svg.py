"""Inline SVG for C4 views and charts. Pure functions from content dicts to HTML.

Diagrams are a grid: each node names a column and row, and edges are straight lines
clipped to the box borders. On phones the SVG is hidden by CSS and a text list of the
same nodes and edges is shown instead, because a 4-column diagram scaled to 375 px is
unreadable.
"""

from __future__ import annotations

from study.text import esc, inline, wrap

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


def diagram_html(view: dict, uid: str) -> str:
    nodes = {n["id"]: n for n in view["nodes"]}
    cols = max(n["col"] for n in nodes.values()) + 1
    rows = max(n["row"] for n in nodes.values()) + 1
    edges = view.get("edges", [])
    # Widen the column gap so a label on a same-row edge fits between the two boxes.
    gx = max([GX] + [round(len(line) * CHAR) + 16 for e in edges
                     if nodes[e["from"]]["row"] == nodes[e["to"]]["row"]
                     for line in wrap(e.get("label", ""), LABEL_CHARS)])
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
        lines = wrap(e.get("label", ""), LABEL_CHARS)
        for i, line in enumerate(lines):
            y = (y1 + y2) / 2 - 5 - (len(lines) - 1 - i) * 13
            p.append(f'<text class="elabel" x="{(x1 + x2) / 2:.1f}" '
                     f'y="{y:.1f}" text-anchor="middle">{esc(line)}</text>')
    for n in nodes.values():
        cx, cy = center(n)
        kind = n.get("kind", "system")
        p.append(f'<g class="node k-{kind}"><rect x="{cx - W / 2:.1f}" y="{cy - H / 2:.1f}" '
                 f'width="{W}" height="{H}" rx="8"/>')
        sub = wrap(n.get("sub", ""), 30)[:2]
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
        kind = n.get("kind", "system")
        # The list keeps the diagram's emphasis: the focus is bold and marked, an
        # external system says so (on the SVG that is a dashed border).
        if kind == "focus":
            name = f'<strong>{esc(n["label"])}</strong> <small class="kmark">key step</small>'
        elif kind == "external":
            name = f"{esc(n['label'])} <small>(external)</small>"
        else:
            name = esc(n["label"])
        text.append(f"<li>{name}{sub}</li>")
    text.append("</ul><ol>")
    for e in edges:
        lab = f": {esc(e['label'])}" if e.get("label") else ""
        text.append(f'<li>{esc(nodes[e["from"]]["label"])} → '
                    f'{esc(nodes[e["to"]]["label"])}{lab}</li>')
    text.append("</ol></div>")
    return "".join(p) + "".join(text)


def _num(v: float) -> str:
    """Up to two decimals, trailing zeros dropped: 19.01, 15.68, 4, 35,792."""
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _signed(v: float) -> str:
    """_num with a true minus sign, for text drawn in a chart."""
    return ("\u2212" + _num(-v)) if v < 0 else _num(v)


def _fit(x: float, text: str, width: float, anchor: str = "middle") -> float:
    """Shift a text's anchor x so its estimated extent stays inside 0..width."""
    w = len(text) * CHART_CHAR
    left = {"end": x - w, "middle": x - w / 2}.get(anchor, x)
    return x + max(0.0, -left) - max(0.0, left + w - width)


def interval_html(chart: dict) -> str:
    """One row per estimate: a dot at the estimate, a whisker from low to high, and a
    labelled zero line, on one horizontal axis that always includes zero.

    The low and high values print just outside the whisker ends, the estimate (with its
    unit) under the dot. Optional `left_label` / `right_label` say what each side of zero
    means and print under the axis; optional `shade` tints that side of zero.
    """
    unit, rows = chart["unit"], chart["rows"]
    lows = [_signed(r["low"]) for r in rows]
    highs = [_signed(r["high"]) for r in rows]
    left_pad = max(len(t) for t in lows) * CHART_CHAR + 10
    right_pad = max(len(t) for t in highs) * CHART_CHAR + 10
    plot = 280.0
    lo = min(0.0, *(r["low"] for r in rows))
    hi = max(0.0, *(r["high"] for r in rows))
    pad = (hi - lo) * 0.06 or 1.0
    lo, hi = lo - pad, hi + pad
    left_txt = f"\u2190 {chart['left_label']}" if chart.get("left_label") else ""
    right_txt = f"{chart['right_label']} \u2192" if chart.get("right_label") else ""
    # Long side labels stack on two lines instead of widening the chart: a wider viewBox
    # shrinks every label on a phone below a readable size.
    width = max(left_pad + plot + right_pad,
                max(len(r["label"]) for r in rows) * CHART_CHAR + 4,
                len(left_txt) * CHART_CHAR + 4, len(right_txt) * CHART_CHAR + 4)

    def x(v):
        return left_pad + (v - lo) / (hi - lo) * plot

    x0 = x(0.0)
    zero_txt = chart.get("zero_label", "")
    top = 26 if zero_txt else 6
    pitch = 66
    axis_y = top + len(rows) * pitch + 2
    # Side labels sit either side of zero; if they would collide, the right one drops a line.
    lx = _fit(x0 - 8, left_txt, width, "end")
    rx = _fit(x0 + 8, right_txt, width, "start")
    two_lines = bool(left_txt and right_txt and rx < lx + 8)
    height = axis_y + (20 if left_txt or right_txt else 4) + (18 if two_lines else 0) + 4
    summary = "; ".join(f"{r['label']}: {_signed(r['estimate'])} {unit}, from "
                        f"{_signed(r['low'])} to {_signed(r['high'])}" for r in rows)
    p = [(f'<svg class="chart interval" viewBox="0 0 {width:.0f} {height:.0f}" role="img" '
          f'aria-label="{esc(f"Interval chart ({unit}). {summary}")}" '
          'xmlns="http://www.w3.org/2000/svg">')]
    if chart.get("shade"):
        sx, sw = ((left_pad, x0 - left_pad) if chart["shade"] == "left"
                  else (x0, left_pad + plot - x0))
        p.append(f'<rect class="shade" x="{sx:.1f}" y="{top - 4}" width="{sw:.1f}" '
                 f'height="{axis_y - top + 4}"/>')
    p.append(f'<line class="axis" x1="{left_pad:.1f}" y1="{axis_y}" '
             f'x2="{left_pad + plot:.1f}" y2="{axis_y}"/>')
    p.append(f'<line class="zero" x1="{x0:.1f}" y1="{top - 6}" x2="{x0:.1f}" y2="{axis_y + 4}"/>')
    if zero_txt:
        p.append(f'<text class="axlabel" x="{_fit(x0, zero_txt, width):.1f}" y="{top - 12}" '
                 f'text-anchor="middle">{esc(zero_txt)}</text>')
    for i, r in enumerate(rows):
        y = top + i * pitch
        xl, xe, xh = x(r["low"]), x(r["estimate"]), x(r["high"])
        est = f"{_signed(r['estimate'])} {unit}"
        p.append(f'<text class="blabel ilabel" x="0" y="{y + 14}">{esc(r["label"])}</text>')
        p.append(f'<line class="whisker" x1="{xl:.1f}" y1="{y + 34}" x2="{xh:.1f}" y2="{y + 34}"/>')
        for cx in (xl, xh):
            p.append(f'<line class="whisker" x1="{cx:.1f}" y1="{y + 28}" x2="{cx:.1f}" '
                     f'y2="{y + 40}"/>')
        p.append(f'<circle class="est" cx="{xe:.1f}" cy="{y + 34}" r="6">'
                 f'<title>{esc(r["label"])}: {esc(est)}</title></circle>')
        p.append(f'<text class="inum" x="{xl - 8:.1f}" y="{y + 39}" '
                 f'text-anchor="end">{lows[i]}</text>')
        p.append(f'<text class="inum" x="{xh + 8:.1f}" y="{y + 39}">{highs[i]}</text>')
        p.append(f'<text class="btotal iest" x="{_fit(xe, est, width):.1f}" y="{y + 60}" '
                 f'text-anchor="middle">{esc(est)}</text>')
    if left_txt:
        p.append(f'<text class="axlabel" x="{lx:.1f}" y="{axis_y + 18}" '
                 f'text-anchor="end">{esc(left_txt)}</text>')
    if right_txt:
        ry = axis_y + 18 + (18 if two_lines else 0)
        rx = _fit(x0 + 8, right_txt, width, "start")
        p.append(f'<text class="axlabel" x="{rx:.1f}" y="{ry}">{esc(right_txt)}</text>')
    p.append("</svg>")
    return "".join(p)


def chart_html(chart: dict, uid: str) -> str:
    """Horizontal bars. `stacked_bars` stacks named segments; `bars` is one bar per item.

    A plain bar prints its value at the tip. A stacked bar prints its summed total there
    only if the chart dict has `"show_totals": true`: a sum of per-phase medians is not
    the median total, so by default it is left off. An `interval` chart is drawn by
    interval_html.
    """
    if chart["type"] == "interval":
        return interval_html(chart)
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
    show_end = not stacked or chart.get("show_totals") is True
    lit = set(chart.get("highlight") or [])

    def dim(name):
        return " dim" if lit and name not in lit else ""

    # Leave room after the longest bar for the longest end label, so none is clipped.
    tail = (max(len(f"{_num(t)} {chart['unit']}") for t in totals) * CHART_CHAR + 6
            if show_end else 0)
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
            p.append(f'<rect class="seg s{cls}{dim(name)}" x="{x:.1f}" y="{y + 20}" width="{drawn:.1f}" '
                     f'height="24" rx="2"><title>{esc(name)}: {_num(v)} {unit}</title></rect>')
            # A plain bar's value is its total, shown at the tip; label stacked segments only.
            if stacked and drawn >= len(_num(v)) * CHART_CHAR + 8:
                p.append(f'<text class="segtext s{cls}{dim(name)}" x="{x + drawn / 2:.1f}" y="{y + 36}" '
                         f'text-anchor="middle">{_num(v)}</text>')
            x += w
        if show_end:
            p.append(f'<text class="btotal" x="{x + 6:.1f}" y="{y + 36}">'
                     f'{_num(total)} {unit}</text>')
    p.append("</svg>")
    legend = ""
    if stacked:
        chips = "".join(f'<li><span class="chip s{i % 8}{dim(n)}"></span>{esc(n)}</li>'
                        for i, n in enumerate(names))
        legend = f'<ul class="legend">{chips}</ul>'
    if chart.get("deltas"):
        items = "".join(f'<li><b>{esc(d["between"])}</b> {inline(d["text"])}</li>'
                        for d in chart["deltas"])
        legend += (f'<div class="deltas"><div class="dhead">What changed between the bars</div>'
                   f'<ul>{items}</ul></div>')
    return "".join(p) + legend
