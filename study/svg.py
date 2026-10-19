"""Inline SVG for C4 views and charts. Pure functions from content dicts to HTML.

Diagrams are a grid: each node names a column and row, and edges are straight lines
clipped to the box borders. On phones the SVG is hidden by CSS and a text list of the
same nodes and edges is shown instead, because a 4-column diagram scaled to 375 px is
unreadable.
"""

from __future__ import annotations

import math

from study.schema import merged_segments
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


def _edge_label_spots(x1, y1, x2, y2, n):
    """Candidate places for an edge's n label lines, best first, each a (points,
    text-anchor) pair; every candidate sits off the line, so its halo never covers it:

    - a horizontal edge: centred, the last line's baseline 8 px above the line (then below);
    - a vertical edge: beside it, 8 px to the right, centred on its middle (then left);
    - a diagonal edge: 10 px out along the normal that points up (then down), anchored
      so the text runs away from the line.
    """
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    if abs(dy) < 1:
        return [([(mx, my - 8 - (n - 1 - i) * 13) for i in range(n)], "middle"),
                ([(mx, my + 18 + i * 13) for i in range(n)], "middle")]
    if abs(dx) < 1:
        ys = [my + 4 - (n - 1) * 6.5 + i * 13 for i in range(n)]
        return [([(mx + 8, y) for y in ys], "start"), ([(mx - 8, y) for y in ys], "end")]
    length = math.hypot(dx, dy)
    nx, ny = dy / length, -dx / length
    if ny > 0:
        nx, ny = -nx, -ny
    up = ([(mx + nx * 10, my + ny * 10 - (n - 1 - i) * 13) for i in range(n)],
          "start" if nx > 0 else "end")
    down = ([(mx - nx * 10, my - ny * 10 + 10 + i * 13) for i in range(n)],
            "end" if nx > 0 else "start")
    return [up, down]


def _label_box(points, anchor, lines):
    """The estimated (left, top, right, bottom) of label lines drawn at points."""
    w = max(len(line) for line in lines) * CHAR
    xs = [x for x, _ in points]
    left = {"end": xs[0] - w, "middle": xs[0] - w / 2}.get(anchor, xs[0])
    return left, min(y for _, y in points) - 11, left + w, max(y for _, y in points) + 3


def _overlaps(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


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
    boxes = [(cx - W / 2, cy - H / 2, cx + W / 2, cy + H / 2)
             for cx, cy in (center(n) for n in nodes.values())]
    labels = []
    for e in edges:
        (ax, ay), (bx, by) = center(nodes[e["from"]]), center(nodes[e["to"]])
        x1, y1 = _clip(ax, ay, bx, by, W / 2 + 2, H / 2 + 2)
        x2, y2 = _clip(bx, by, ax, ay, W / 2 + 6, H / 2 + 6)
        p.append(f'<line class="edge" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" '
                 f'y2="{y2:.1f}" marker-end="url(#arr-{esc(uid)})"/>')
        lines = wrap(e.get("label", ""), LABEL_CHARS)
        if not lines:
            continue
        options = _edge_label_spots(x1, y1, x2, y2, len(lines))
        # The first spot that clears every box; else the first, drawn over the boxes.
        spots, anchor = next(
            (o for o in options
             if not any(_overlaps(_label_box(*o, lines), b) for b in boxes)), options[0])
        labels += [f'<text class="elabel" x="{lx:.1f}" y="{ly:.1f}" '
                   f'text-anchor="{anchor}">{esc(line)}</text>'
                   for (lx, ly), line in zip(spots, lines)]
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
    # Labels go last, above the boxes: one that cannot avoid a box is still readable.
    p += labels
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


def _decimals(v: float) -> int:
    """Decimal places in a value as written (JSON drops trailing zeros: -20.30 is -20.3)."""
    text = repr(float(v))
    return 0 if "e" in text else len(text.split(".")[1].rstrip("0"))


def _row_fmt(row: dict):
    """An interval row's number format: its `decimals`, else the most decimal places any
    of its three values has, so -10.39, -20.3, -5.54 print as -10.39, -20.30, -5.54."""
    d = row.get("decimals")
    if d is None:
        d = max(_decimals(row[k]) for k in ("low", "estimate", "high"))

    def fmt(v):
        text = f"{abs(v):,.{d}f}"
        return ("\u2212" + text) if v < 0 and float(text.replace(",", "")) != 0 else text
    return fmt


def _fit(x: float, text: str, width: float, anchor: str = "middle") -> float:
    """Shift a text's anchor x so its estimated extent stays inside 0..width."""
    w = len(text) * CHART_CHAR
    left = {"end": x - w, "middle": x - w / 2}.get(anchor, x)
    return x + max(0.0, -left) - max(0.0, left + w - width)


def _split(text: str) -> list[str]:
    """Two lines, split at the word break that makes the longer line shortest."""
    words = text.split()
    if len(words) < 2:
        return [text]
    cuts = [(" ".join(words[:i]), " ".join(words[i:])) for i in range(1, len(words))]
    return list(min(cuts, key=lambda c: max(len(c[0]), len(c[1]))))


def _half(text: str) -> int:
    """Characters in the longer line of _split(text)."""
    return max(len(line) for line in _split(text))


def interval_html(chart: dict) -> str:
    """One row per estimate: a dot at the estimate, a whisker from low to high, and a
    labelled zero line, on one horizontal axis that always includes zero.

    The low and high values print just outside the whisker ends, the estimate (with its
    unit) under the dot. Optional `left_label` / `right_label` say what each side of zero
    means and print under the axis; optional `shade` tints that side of zero.
    """
    unit, rows = chart["unit"], chart["rows"]
    fmts = [_row_fmt(r) for r in rows]
    lows = [f(r["low"]) for f, r in zip(fmts, rows)]
    highs = [f(r["high"]) for f, r in zip(fmts, rows)]
    left_pad = max(len(t) for t in lows) * CHART_CHAR + 10
    right_pad = max(len(t) for t in highs) * CHART_CHAR + 10
    plot = 280.0
    lo = min(0.0, *(r["low"] for r in rows))
    hi = max(0.0, *(r["high"] for r in rows))
    span = hi - lo or 1.0
    lo, hi = lo - span * 0.06, hi + span * 0.06
    left_txt = f"\u2190 {chart['left_label']}" if chart.get("left_label") else ""
    right_txt = f"{chart['right_label']} \u2192" if chart.get("right_label") else ""
    # Each side label sits on its own side of zero, on two lines if it must. When the
    # data hugs zero, the axis runs on past zero (at least a fifth of the data span) so
    # that side exists on the chart and has room for the longer half of its label.
    need_l = (_half(left_txt) * CHART_CHAR + 8) if left_txt else 0.0
    need_r = (_half(right_txt) * CHART_CHAR + 8) if right_txt else 0.0
    if left_txt:
        lo = min(lo, -span * 0.2)
    if right_txt:
        hi = max(hi, span * 0.2)
    f_r = min(0.6, max(0.0, need_r - right_pad) / plot)  # share of the plot right of zero
    if hi / (hi - lo) < f_r:
        hi = -f_r * lo / (1 - f_r)
    f_l = min(0.6, max(0.0, need_l - left_pad) / plot)  # share of the plot left of zero
    if -lo / (hi - lo) < f_l:
        lo = -f_l * hi / (1 - f_l)
    # A wider viewBox shrinks every label on a phone below a readable size, so long side
    # labels wrap instead of widening the chart.
    width = max(left_pad + plot + right_pad, max(len(r["label"]) for r in rows) * CHART_CHAR + 4)

    def x(v):
        return left_pad + (v - lo) / (hi - lo) * plot

    x0 = x(0.0)
    zero_txt = chart.get("zero_label", "")
    top = 26 if zero_txt else 6
    pitch = 66
    axis_y = top + len(rows) * pitch + 2

    def side(txt, room):
        if not txt or len(txt) * CHART_CHAR <= room:
            return [txt] if txt else []
        return _split(txt)

    l_lines = side(left_txt, x0 - 8)
    r_lines = side(right_txt, width - x0 - 8)
    n_lines = max(len(l_lines), len(r_lines))
    height = axis_y + 18 * n_lines + 6
    summary = "; ".join(f"{r['label']}: {f(r['estimate'])} {unit}, from "
                        f"{f(r['low'])} to {f(r['high'])}" for f, r in zip(fmts, rows))
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
        est = f"{fmts[i](r['estimate'])} {unit}"
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
    for k, line in enumerate(l_lines):
        p.append(f'<text class="axlabel sidel" x="{x0 - 8:.1f}" y="{axis_y + 18 + 18 * k}" '
                 f'text-anchor="end">{esc(line)}</text>')
    for k, line in enumerate(r_lines):
        p.append(f'<text class="axlabel sider" x="{x0 + 8:.1f}" y="{axis_y + 18 + 18 * k}" '
                 f'text-anchor="start">{esc(line)}</text>')
    p.append("</svg>")
    caption = ""
    if chart.get("shade"):
        side = chart.get(f"{chart['shade']}_label")
        text = chart.get("shade_caption") or (
            f"shaded: the side where {side}" if side
            else f"shaded: the {chart['shade']} side of zero")
        caption = f'<p class="cnote"><span class="shswatch"></span>{inline(text)}</p>'
    return "".join(p) + caption


P_LEFT, P_PLOT, P_RIGHT = 14, 360, 16  # percentile chart margins and plot width
P_LANE = 17  # vertical step between stacked labels of one row
SHAPES = 4  # percentile marks cycle through four shapes and colours (--c0, c1, c6, c3)


def _ticks(hi: float) -> list[float]:
    """Round tick values from zero up to hi: steps of 1, 2, 2.5 or 5 times a power of ten,
    about four of them."""
    raw = hi / 4
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    return [k * step for k in range(int(hi / step + 1e-9) + 1)]


def _mark(k: int, x: float, y: float) -> str:
    """Path data for percentile style k: circle, diamond, square, triangle."""
    shape = k % SHAPES
    if shape == 0:
        return f"M{x - 6:.1f} {y:.1f}a6 6 0 1 0 12 0a6 6 0 1 0 -12 0z"
    if shape == 1:
        return f"M{x:.1f} {y - 7:.1f}L{x + 7:.1f} {y:.1f}L{x:.1f} {y + 7:.1f}L{x - 7:.1f} {y:.1f}z"
    if shape == 2:
        return f"M{x - 5.5:.1f} {y - 5.5:.1f}h11v11h-11z"
    return f"M{x:.1f} {y - 7:.1f}L{x + 7:.1f} {y + 5:.1f}L{x - 7:.1f} {y + 5:.1f}z"


def _lanes(items: list[tuple[float, str]], width: float) -> list[tuple[str, int, float]]:
    """Place each (x, text) label above or below its mark, in the nearest free lane.

    Labels are tried above in lane 0, then below in lane 0, then above in lane 1, and so
    on, taking the first spot where the label's estimated extent (kept inside the chart)
    clears every label already in that lane by 6 px. Returns (side, lane, anchor x)."""
    taken: dict[tuple[str, int], list[tuple[float, float]]] = {}
    out = []
    for x, text in items:
        ax = _fit(x, text, width)
        half = len(text) * CHART_CHAR / 2
        lo, hi = ax - half, ax + half
        lane = 0
        while True:
            spot = next((s for s in ("above", "below")
                         if all(hi + 6 <= a or lo >= b + 6 for a, b in taken.get((s, lane), []))),
                        None)
            if spot:
                taken.setdefault((spot, lane), []).append((lo, hi))
                out.append((spot, lane, ax))
                break
            lane += 1
    return out


def percentiles_html(chart: dict) -> str:
    """One row per label on one shared axis from zero: a thin line from the row's lowest
    to its highest percentile, a mark per percentile (one shape and colour per percentile
    name) labelled with its name and value, and optionally a hollow marker for the row's
    largest value (`max_label`), joined by a dashed line, so one outlier can be shown
    without stretching the percentiles. Labels that would collide move to the other side
    of the line, then further out."""
    unit, rows = chart["unit"], chart["rows"]
    names = list(dict.fromkeys(v["name"] for r in rows for v in r["values"]))
    top = max(max([v["value"] for v in r["values"]] + [r.get("max_label", {}).get("value", 0)])
              for r in rows)
    hi = (top or 1.0) * 1.06
    width = P_LEFT + P_PLOT + P_RIGHT

    def x(v):
        return P_LEFT + v / hi * P_PLOT

    body, y = [], 0.0
    for r in rows:
        items = [(x(v["value"]), f"{v['name']} {_num(v['value'])}") for v in r["values"]]
        m = r.get("max_label")
        if m:
            items.append((x(m["value"]), f"{m['text']} {_num(m['value'])}"))
        order = sorted(range(len(items)), key=lambda i: items[i][0])
        placed = dict(zip(order, _lanes([items[i] for i in order], width)))
        above = 1 + max([lane for side, lane, _ in placed.values() if side == "above"],
                        default=-1)
        below = 1 + max([lane for side, lane, _ in placed.values() if side == "below"],
                        default=-1)
        body.append(f'<text class="blabel" x="0" y="{y + 14:.1f}">{esc(r["label"])}</text>')
        cy = y + 20 + P_LANE * above + 10
        vals = [v["value"] for v in r["values"]]
        body.append(f'<line class="prange" x1="{x(min(vals)):.1f}" y1="{cy:.1f}" '
                    f'x2="{x(max(vals)):.1f}" y2="{cy:.1f}"/>')
        if m:
            body.append(f'<line class="pgap" x1="{x(max(vals)):.1f}" y1="{cy:.1f}" '
                        f'x2="{x(m["value"]):.1f}" y2="{cy:.1f}"/>')
            body.append(f'<circle class="pmax" cx="{x(m["value"]):.1f}" cy="{cy:.1f}" r="6">'
                        f'<title>{esc(r["label"])}: {esc(m["text"])} {_num(m["value"])} '
                        f'{esc(unit)}</title></circle>')
        for v in r["values"]:
            k = names.index(v["name"]) % SHAPES
            body.append(f'<path class="pdot pk{k}" data-x="{x(v["value"]):.1f}" '
                        f'd="{_mark(k, x(v["value"]), cy)}"><title>{esc(r["label"])}: '
                        f'{esc(v["name"])} {_num(v["value"])} {esc(unit)}</title></path>')
        for i, (side, lane, ax) in placed.items():
            ty = cy - 12 - P_LANE * lane if side == "above" else cy + 24 + P_LANE * lane
            cls = "pnum pmaxt" if m and i == len(items) - 1 else "pnum"
            body.append(f'<text class="{cls}" x="{ax:.1f}" y="{ty:.1f}" '
                        f'text-anchor="middle">{esc(items[i][1])}</text>')
        y = cy + 10 + P_LANE * below + (10 if below else 4)
    axis_y = y + 4
    ticks = _ticks(hi)
    grid = "".join(f'<line class="pgrid" x1="{x(t):.1f}" y1="0" x2="{x(t):.1f}" '
                   f'y2="{axis_y:.1f}"/>' for t in ticks)
    axis = [(f'<line class="paxis" x1="{x(0):.1f}" y1="{axis_y:.1f}" x2="{x(hi):.1f}" '
             f'y2="{axis_y:.1f}"/>')]
    for j, t in enumerate(ticks):
        label = _num(t) + (f" {unit}" if j == len(ticks) - 1 else "")
        axis.append(f'<line class="paxis" x1="{x(t):.1f}" y1="{axis_y:.1f}" x2="{x(t):.1f}" '
                    f'y2="{axis_y + 5:.1f}"/>')
        axis.append(f'<text class="axlabel ptick" x="{_fit(x(t), label, width):.1f}" '
                    f'y="{axis_y + 21:.1f}" text-anchor="middle">{esc(label)}</text>')
    height = axis_y + 28
    summary = "; ".join(
        f"{r['label']}: " + ", ".join(f"{v['name']} {_num(v['value'])}" for v in r["values"])
        + (f"; {r['max_label']['text']} {_num(r['max_label']['value'])}"
           if r.get("max_label") else "") for r in rows)
    out = (f'<svg class="chart percentiles" viewBox="0 0 {width} {height:.0f}" role="img" '
           f'aria-label="{esc(f"Percentiles ({unit}). {summary}")}" '
           f'xmlns="http://www.w3.org/2000/svg">{grid}{"".join(body)}{"".join(axis)}</svg>')
    return out + _note(chart)


def _note(chart: dict) -> str:
    return f'<p class="cnote">{inline(chart["note"])}</p>' if chart.get("note") else ""


def _segment_names(chart: dict) -> list[str]:
    """The names a stacked chart draws (merged groups by their label), in order."""
    return list(dict.fromkeys(n for b in chart["bars"] for n, _, _ in merged_segments(chart, b)))


def _ghost_geometry(chart: dict) -> tuple[str, float, float] | None:
    """(on_bar label, start value, width value) of a chart's ghost outline, or None.

    The outline is as wide as the segment was in from_bar and starts where that segment
    starts in on_bar (or at on_bar's end, if on_bar does not have it)."""
    g = chart.get("ghost")
    if not g:
        return None
    bars = {b["label"]: merged_segments(chart, b) for b in chart["bars"]}
    width = next(v for n, v, _ in bars[g["from_bar"]] if n == g["segment"])
    start = 0.0
    for n, v, _ in bars[g["on_bar"]]:
        if n == g["segment"]:
            break
        start += v
    return g["on_bar"], start, width


# Cold-start phases and memory parts that recur across units keep one colour on every
# page. "Everything else" shares slot 2 with the platform residual: the two never meet in
# one chart today, and if they do, segment_slots moves the later one to a free slot.
CANONICAL_SEGMENT_SLOTS = {
    "Server launch to model loaded": 0,
    "Compile": 1,
    "Platform (by subtraction)": 2,
    "Graph capture": 3,
    "Memory profiling": 4,
    "Ready check": 5,
    "First request": 6,
    "Weights": 7,
    "Everything else: scratch space and the KV cache": 2,
}


def segment_slots(charts: list[dict]) -> dict[str, int]:
    """One colour slot (0-7) per segment name across a page's stacked charts.

    Canonical names (CANONICAL_SEGMENT_SLOTS) go first and take their fixed slot, so a
    phase is the same colour on every page; if that slot is already used by another name
    in the same chart, the name takes the lowest slot no name in that chart uses or
    claims. Other names then take slots in order of first appearance: the lowest slot no
    name on the page uses, or once all eight are used, the lowest no other name in its
    chart has."""
    slots: dict[str, int] = {}
    for chart in charts:
        names = _segment_names(chart)
        claimed = {slots[n] for n in names if n in slots}
        wanted = [n for n in names if n not in slots and n in CANONICAL_SEGMENT_SLOTS]
        clashed = []
        for name in wanted:
            k = CANONICAL_SEGMENT_SLOTS[name]
            if k in claimed:
                clashed.append(name)
            else:
                slots[name] = k
                claimed.add(k)
        reserved = {CANONICAL_SEGMENT_SLOTS[n] for n in names if n in CANONICAL_SEGMENT_SLOTS}
        for name in clashed:
            free = ([k for k in range(8) if k not in claimed | reserved]
                    or [k for k in range(8) if k not in claimed] or [0])
            slots[name] = free[0]
            claimed.add(free[0])
    for chart in charts:
        names = _segment_names(chart)
        for name in names:
            if name in slots:
                continue
            taken = {slots[n] for n in names if n in slots}
            free = [k for k in range(8) if k not in set(slots.values())]
            free = free or [k for k in range(8) if k not in taken]
            slots[name] = free[0] if free else len(slots) % 8
    return slots


def chart_html(chart: dict, uid: str, slots: dict[str, int] | None = None) -> str:
    """Horizontal bars. `stacked_bars` stacks named segments; `bars` is one bar per item.

    `slots` maps a segment name to its colour slot (see segment_slots); without it a
    stacked chart colours its segments by their order in the chart.

    A plain bar prints its value at the tip. A stacked bar prints its summed total there
    only if the chart dict has `"show_totals": true`: a sum of per-phase medians is not
    the median total, so by default it is left off. An `interval` chart is drawn by
    interval_html.
    """
    if chart["type"] == "interval":
        return interval_html(chart)
    if chart["type"] == "percentiles":
        return percentiles_html(chart)
    if chart["type"] == "xy":
        from study.xy import xy_html  # study.xy imports this module's helpers
        return xy_html(chart)
    unit = esc(chart["unit"])
    stacked = chart["type"] == "stacked_bars"
    if stacked:
        bars = [(b["label"], merged_segments(chart, b)) for b in chart["bars"]]
    else:
        bars = [(i["label"], [(i["label"], i["value"], [])]) for i in chart["items"]]
    totals = [sum(v for _, v, _ in segs) for _, segs in bars]
    names = list(dict.fromkeys(n for _, segs in bars for n, _, _ in segs))
    slot = slots or {n: i % 8 for i, n in enumerate(names)}
    full, pitch = 340.0, 58
    ghost = _ghost_geometry(chart) if stacked else None
    scale = full / max(totals + ([ghost[1] + ghost[2]] if ghost else []))
    # The bar with a ghost outline gets an extra line under it for the outline's caption.
    tops, y = [], 0
    for label, _ in bars:
        tops.append(y)
        y += pitch + (16 if ghost and label == ghost[0] else 0)
    height = y + 4
    show_end = not stacked or chart.get("show_totals") is True
    lit = set(chart.get("highlight") or [])
    # Highlighting a merged member lights the merged segment it is drawn in.
    lit |= {g["label"] for g in chart.get("merge", []) if lit & set(g["names"])}

    def dim(name):
        return " dim" if lit and name not in lit else ""

    # Leave room after the longest bar for the longest end label, so none is clipped.
    tail = (max(len(f"{_num(t)} {chart['unit']}") for t in totals) * CHART_CHAR + 6
            if show_end else 0)
    width = round(full + 6 + tail)
    p = [(f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
          f'aria-label="{unit} by bar" xmlns="http://www.w3.org/2000/svg">')]
    for (label, segs), total, y in zip(bars, totals, tops):
        p.append(f'<text class="blabel" x="0" y="{y + 14}">{esc(label)}</text>')
        x = 0.0
        for name, v, members in segs:
            w = v * scale
            cls = slot[name] if stacked else 0
            # A 2 px surface gap separates touching segments; a sliver keeps its width.
            drawn = w - GAP if w > 2 * GAP else w
            parts = (" (" + " + ".join(f"{esc(m)} {_num(mv)}" for m, mv in members) + ")"
                     if len(members) > 1 else "")
            p.append(f'<rect class="seg s{cls}{dim(name)}" x="{x:.1f}" y="{y + 20}" width="{drawn:.1f}" '
                     f'height="24" rx="2"><title>{esc(name)}: {_num(v)} {unit}{parts}</title></rect>')
            # A plain bar's value is its total, shown at the tip; label stacked segments only,
            # greyed ones too (in a muted ink), so a flat phase stays visible as a number.
            if stacked and drawn >= len(_num(v)) * CHART_CHAR + 4:
                p.append(f'<text class="segtext s{cls}{dim(name)}" x="{x + drawn / 2:.1f}" y="{y + 36}" '
                         f'text-anchor="middle">{_num(v)}</text>')
            x += w
        if show_end:
            p.append(f'<text class="btotal" x="{x + 6:.1f}" y="{y + 36}">'
                     f'{_num(total)} {unit}</text>')
        if ghost and label == ghost[0]:
            g = chart["ghost"]
            gx, gw = ghost[1] * scale, ghost[2] * scale
            cap = f"was {_num(ghost[2])} {chart['unit']} in {g['from_bar']}"
            p.append(f'<rect class="ghost" x="{gx:.1f}" y="{y + 19}" width="{gw:.1f}" '
                     f'height="26" rx="3"><title>{esc(g["segment"])} {esc(cap)}</title></rect>')
            p.append(f'<text class="gcap" x="{_fit(gx, cap, width, "start"):.1f}" y="{y + 60}" '
                     f'text-anchor="start">{esc(cap)}</text>')
    p.append("</svg>")
    legend = ""
    if stacked:
        chips = "".join(f'<li><span class="chip s{slot[n]}{dim(n)}"></span>{esc(n)}</li>'
                        for n in names)
        legend = f'<ul class="legend">{chips}</ul>'
    if chart.get("deltas"):
        items = "".join(f'<li><b>{esc(d["between"])}</b> {inline(d["text"])}</li>'
                        for d in chart["deltas"])
        legend += (f'<div class="deltas"><div class="dhead">What changed between the bars</div>'
                   f'<ul>{items}</ul></div>')
    return "".join(p) + legend
