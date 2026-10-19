"""Inline SVG for charts on two numeric axes: `xy` (line, point and step series).

Sizing: the viewBox is W units wide. A 375 px phone leaves a card 309 px of content, and
phone CSS sets chart text to 15 units, so text renders at 309 / 386 * 15 = 12 px. Every
text's extent is estimated at CHART_CHAR units per character and kept inside the viewBox.

Identity is never colour alone: series k has colour class xk<k> (page CSS maps xk0..xk5 to
the palette slots c0, c1, c6, c2, c3, c4, an order that passes the dataviz validator's
adjacent-pair colour-blindness check in light and dark) and marker shape SHAPES[k]. On a
dual chart, series on the right axis are dashed with hollow markers, and say so in the
legend.
"""

from __future__ import annotations

import math

from study.svg import CHART_CHAR, _fit, _note, _num, _overlaps
from study.text import esc, wrap

W = 386  # viewBox width (see the module docstring)
PLOT_H = 210  # plot height
PAD = 10  # inner x padding, so a marker at either end clears the axes
LINE = 18  # pitch of one line of chart text
TITLE_CHARS = int(W / CHART_CHAR)
SHAPES = ("circle", "diamond", "square", "triangle", "triangle-down", "cross")


def shape_path(name: str, x: float, y: float, s: float = 1.0) -> str:
    """Path data for a marker of the named shape centred on (x, y), about 10 units across
    at scale s = 1."""
    if name == "circle":
        r = 5 * s
        return (f"M{x - r:.1f} {y:.1f}a{r:.1f} {r:.1f} 0 1 0 {2 * r:.1f} 0"
                f"a{r:.1f} {r:.1f} 0 1 0 {-2 * r:.1f} 0z")
    if name == "diamond":
        r = 6.5 * s
        return f"M{x:.1f} {y - r:.1f}L{x + r:.1f} {y:.1f}L{x:.1f} {y + r:.1f}L{x - r:.1f} {y:.1f}z"
    if name == "square":
        r = 4.5 * s
        return f"M{x - r:.1f} {y - r:.1f}h{2 * r:.1f}v{2 * r:.1f}h{-2 * r:.1f}z"
    if name in ("triangle", "triangle-down"):
        r, f = 6 * s, (1 if name == "triangle" else -1)
        return (f"M{x:.1f} {y - f * r:.1f}L{x + r:.1f} {y + f * r * 0.75:.1f}"
                f"L{x - r:.1f} {y + f * r * 0.75:.1f}z")
    a, b = 6 * s, 2.2 * s  # cross: a plus sign
    pts = [(-b, -a), (b, -a), (b, -b), (a, -b), (a, b), (b, b), (b, a), (-b, a), (-b, b),
           (-a, b), (-a, -b), (-b, -b)]
    return "M" + "L".join(f"{x + dx:.1f} {y + dy:.1f}" for dx, dy in pts) + "z"


def plain(v: float) -> str:
    """Up to six decimals, trailing zeros dropped, a true minus sign: axis ticks and x."""
    t = f"{abs(v):,.6f}".rstrip("0").rstrip(".")
    return ("−" + t) if v < 0 and t != "0" else t


def val(v: float) -> str:
    """A value label: three significant digits below 1 (0.606), else up to two decimals."""
    a = abs(v)
    t = f"{a:.3g}" if 0 < a < 1 else _num(a)
    if "e" in t:
        t = plain(a)
    return ("−" + t) if v < 0 else t


def _with_unit(text: str, unit: str) -> str:
    return f"{text} {unit}" if unit else text


class Axis:
    def __init__(self, lo: float, hi: float, ticks: list[float], log: bool = False):
        self.lo, self.hi, self.ticks, self.log = lo, hi, ticks, log

    def frac(self, v: float) -> float:
        if self.log:
            return (math.log(v) - math.log(self.lo)) / (math.log(self.hi) - math.log(self.lo))
        return (v - self.lo) / (self.hi - self.lo)


def _nice_step(raw: float) -> float:
    """The smallest 1, 2 or 5 times a power of ten that is >= raw."""
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw * (1 - 1e-9))


def _next_step(step: float) -> float:
    mag = 10 ** math.floor(math.log10(step) + 1e-9)
    return {1: 2, 2: 5, 5: 10}[round(step / mag)] * mag


def _span(values: list[float], from_zero: bool) -> tuple[float, float]:
    lo, hi = min(values), max(values)
    if from_zero:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    if hi - lo < 1e-12:
        pad = abs(hi) * 0.5 or 1.0
        lo, hi = (lo, hi + pad) if from_zero and lo == 0 else (lo - pad, hi + pad)
    return lo, hi


def linear_axis(values: list[float], n: int, from_zero: bool) -> Axis:
    """Round 1-2-5 ticks covering the values in about n steps; the axis ends on ticks."""
    lo, hi = _span(values, from_zero)
    step = _nice_step((hi - lo) / n)
    a = math.floor(lo / step + 1e-9) * step
    b = math.ceil(hi / step - 1e-9) * step
    return Axis(a, b, [a + i * step for i in range(round((b - a) / step) + 1)])


def aligned_axis(values: list[float], intervals: int, from_zero: bool) -> Axis:
    """A second y axis with exactly `intervals` 1-2-5 steps, so its ticks share the left
    axis' gridlines."""
    lo, hi = _span(values, from_zero)
    step = _nice_step((hi - lo) / intervals)
    while True:
        a = math.floor(lo / step + 1e-9) * step
        if a + step * intervals >= hi - 1e-9:
            break
        step = _next_step(step)
    return Axis(a, a + step * intervals, [a + i * step for i in range(intervals + 1)])


def _pow2(v: float) -> bool:
    return v > 0 and abs(math.log2(v) - round(math.log2(v))) < 1e-9


def log_axis(values: list[float], data: list[float]) -> Axis:
    """A log axis over the values. Ticks at each power of two when every data x is one
    (a doubling sweep: 1, 2, 4, ... 128), else at 1, 2 and 5 times each power of ten
    (only the powers of ten when that gives more than seven)."""
    lo, hi = min(values), max(values)
    if hi / lo < 1.0001:
        lo, hi = lo / 2, hi * 2
    if all(_pow2(v) for v in data):
        ticks = [2.0 ** k for k in range(math.ceil(math.log2(lo) - 1e-9),
                                         math.floor(math.log2(hi) + 1e-9) + 1)]
    else:
        ticks = [m * 10.0 ** e for e in range(math.floor(math.log10(lo)),
                                              math.ceil(math.log10(hi)) + 1)
                 for m in (1, 2, 5) if lo * (1 - 1e-9) <= m * 10.0 ** e <= hi * (1 + 1e-9)]
        if len(ticks) > 7:
            ticks = [t for t in ticks if abs(math.log10(t) - round(math.log10(t))) < 1e-9]
    if len(ticks) < 2:
        ticks = sorted(set(ticks) | {lo, hi})
    return Axis(lo, hi, ticks, log=True)


def text_box(x: float, y: float, text: str, anchor: str = "start"):
    """Estimated (left, top, right, bottom) of one line of chart text at baseline y."""
    w = len(text) * CHART_CHAR
    left = {"end": x - w, "middle": x - w / 2}.get(anchor, x)
    return left, y - 12, left + w, y + 3


def _text(cls: str, x: float, y: float, text: str, anchor: str = "start") -> str:
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}"{a}>{esc(text)}</text>'


class Frame:
    """The axes, gridlines, bands and reference lines of a chart on two numeric axes, and
    the scales that place data in it.

    xs, ys and ys2 are every value each axis must show (data, whiskers, bands, refs);
    data_xs is the data's x values alone (they choose log ticks). ys2 makes a dual chart:
    a right axis whose ticks share the left axis' gridlines."""

    def __init__(self, chart: dict, xs: list[float], ys: list[float],
                 ys2: list[float] | None = None, data_xs: list[float] | None = None):
        self.chart = chart
        from_zero = chart.get("y_from_zero", True)
        self.xa = (log_axis(xs, data_xs or xs) if chart.get("x_log")
                   else linear_axis(xs, 4, False))
        self.ya = linear_axis(ys, 5, from_zero)
        self.ya2 = aligned_axis(ys2, len(self.ya.ticks) - 1, from_zero) if ys2 else None
        left = max(len(plain(t)) for t in self.ya.ticks) * CHART_CHAR + 8
        right = (max(len(plain(t)) for t in self.ya2.ticks) * CHART_CHAR + 8
                 if self.ya2 else 12)
        self.pl, self.pr = left, W - right
        self.back: list[str] = []  # drawn under the data
        self.labels: list[str] = []  # drawn over it
        self.boxes: list[tuple] = []  # text already placed, for collision checks
        # Band and horizontal reference labels: (class, text, candidate spots), placed by
        # finish() once the markers they must avoid are known.
        self.pending: list[tuple] = []

        # Axis titles over the plot: y on the left, the right axis' on the right.
        unit = chart["unit"]
        t1 = f"{chart['y_label']} ({unit})" if unit else chart["y_label"]
        lines = [(s, 0.0, "start") for s in wrap(t1, TITLE_CHARS)]
        if self.ya2:
            u2 = chart.get("y2_unit", unit)
            t2 = f"{chart['y2_label']} ({u2})" if u2 else chart["y2_label"]
            if len(lines) == 1 and (len(t1) + len(t2)) * CHART_CHAR + 16 <= W:
                lines = [(t1, 0.0, "start", t2)]
            else:
                lines += [(s, float(W), "end") for s in wrap(t2, TITLE_CHARS)]
        y = 14.0
        for line in lines:
            self._label("axlabel xyax", line[1], y, line[0], line[2])
            if len(line) == 4:
                self._label("axlabel xyax", float(W), y, line[3], "end")
            y += LINE
        top = y - LINE + 6

        # Vertical reference lines are labelled above the plot, in as many lanes as needed.
        xrefs = [r for r in chart.get("refs", []) if "x" in r]
        lanes: list[list[tuple]] = []
        placed = []
        for r in xrefs:
            cx = self.x(r["x"])
            ax = _fit(cx, r["label"], W)
            box = text_box(ax, 0, r["label"], "middle")
            lane = next((i for i, spans in enumerate(lanes)
                         if all(box[2] + 6 <= a or box[0] >= b + 6 for a, b in spans)), None)
            if lane is None:
                lanes.append([])
                lane = len(lanes) - 1
            lanes[lane].append((box[0], box[2]))
            placed.append((r, cx, ax, lane))
        self.pt = top + LINE * len(lanes) + 10
        self.pb = self.pt + PLOT_H
        for r, cx, ax, lane in placed:
            ly = top + 14 + LINE * lane
            self.back.append(f'<line class="xyref" x1="{cx:.1f}" y1="{ly + 5:.1f}" '
                             f'x2="{cx:.1f}" y2="{self.pb:.1f}"/>')
            self._label("xyrt", ax, ly, r["label"], "middle")

        # Bands, gridlines, axes, ticks.
        for b in chart.get("bands", []):
            yt, yb = self.y(b["y_hi"]), self.y(b["y_lo"])
            self.back.append(f'<rect class="xyband" x="{self.pl:.1f}" y="{yt:.1f}" '
                             f'width="{self.pr - self.pl:.1f}" height="{yb - yt:.1f}"/>')
            inside = [(self.pl + 6, yt + 14, "start"), (self.pr - 6, yt + 14, "end"),
                      (self.pl + 6, yb - 4, "start"), (self.pr - 6, yb - 4, "end")]
            self.pending.append(("xybt", b["label"], (inside if yb - yt >= LINE else []) + [
                (self.pl + 6, yt - 4, "start"), (self.pr - 6, yt - 4, "end"),
                (self.pl + 6, yb + 14, "start"), (self.pr - 6, yb + 14, "end")]))
        for t in self.ya.ticks[1:]:
            self.back.append(f'<line class="xygrid" data-v="{t:g}" x1="{self.pl:.1f}" '
                             f'y1="{self.y(t):.1f}" x2="{self.pr:.1f}" y2="{self.y(t):.1f}"/>')
        self.back.append(f'<line class="xyaxis" x1="{self.pl:.1f}" y1="{self.pb:.1f}" '
                         f'x2="{self.pr:.1f}" y2="{self.pb:.1f}"/>')
        self.back.append(f'<line class="xyaxis" x1="{self.pl:.1f}" y1="{self.pt:.1f}" '
                         f'x2="{self.pl:.1f}" y2="{self.pb:.1f}"/>')
        if self.ya2:
            self.back.append(f'<line class="xyaxis" x1="{self.pr:.1f}" y1="{self.pt:.1f}" '
                             f'x2="{self.pr:.1f}" y2="{self.pb:.1f}"/>')
        for t in self.ya.ticks:
            self._label("axlabel xyt", self.pl - 6, self.y(t) + 4, plain(t), "end")
        for t in self.ya2.ticks if self.ya2 else []:
            self._label("axlabel xyt", self.pr + 6, self.y2(t) + 4, plain(t), "start")
        right_edge = 0.0
        for t in self.xa.ticks:
            cx = self.x(t)
            self.back.append(f'<line class="xytick" x1="{cx:.1f}" y1="{self.pb:.1f}" '
                             f'x2="{cx:.1f}" y2="{self.pb + 4:.1f}"/>')
            text = plain(t)
            ax = _fit(cx, text, W)
            box = text_box(ax, self.pb + LINE, text, "middle")
            if box[0] >= right_edge + 4:  # thin out labels that would touch
                self._label("axlabel xyt", ax, self.pb + LINE, text, "middle")
                right_edge = box[2]
        xt = chart["x_label"] + (" (log scale)" if chart.get("x_log") else "")
        y = self.pb + 38
        for line in wrap(xt, TITLE_CHARS):
            self._label("axlabel xyax", _fit((self.pl + self.pr) / 2, line, W), y, line,
                        "middle")
            y += LINE
        self.height = y - LINE + 8

        # Horizontal reference lines: dashed across the plot, labelled at the right end.
        for r in chart.get("refs", []):
            if "y" not in r:
                continue
            ry = self.y(r["y"])
            self.back.append(f'<line class="xyref" x1="{self.pl:.1f}" y1="{ry:.1f}" '
                             f'x2="{self.pr:.1f}" y2="{ry:.1f}"/>')
            self.pending.append(("xyrt", r["label"], [
                (self.pr - 4, ry - 5, "end"), (self.pr - 4, ry + 15, "end"),
                (self.pl + 6, ry - 5, "start"), (self.pl + 6, ry + 15, "start"),
                ((self.pl + self.pr) / 2, ry - 5, "middle"),
                ((self.pl + self.pr) / 2, ry + 15, "middle")]))

    def x(self, v: float) -> float:
        return self.pl + PAD + self.xa.frac(v) * (self.pr - self.pl - 2 * PAD)

    def y(self, v: float) -> float:
        return self.pb - self.ya.frac(v) * (self.pb - self.pt)

    def y2(self, v: float) -> float:
        return self.pb - self.ya2.frac(v) * (self.pb - self.pt)

    def _label(self, cls, x, y, text, anchor="start"):
        self.labels.append(_text(cls, x, y, text, anchor))
        self.boxes.append(text_box(x, y, text, anchor))

    def place(self, cls: str, text: str, spots: list[tuple], marks: list[tuple]) -> None:
        """Draw `text` at the first of `spots` [(x, y, anchor)] that lies inside the chart
        above the x axis and clears every label already placed and every marker in
        `marks` [(x, y)]; if none does, at the first that lies inside."""
        dots = [(mx - 7, my - 7, mx + 7, my + 7) for mx, my in marks]
        first = None
        for x, y, anchor in spots:
            box = text_box(x, y, text, anchor)
            if box[0] < -0.5 or box[2] > W + 0.5 or box[1] < 0 or box[3] > self.pb:
                continue
            first = first or (x, y, anchor)
            if not any(_overlaps(box, b) for b in self.boxes + dots):
                self._label(cls, x, y, text, anchor)
                return
        x, y, anchor = first or (_fit(spots[0][0], text, W, spots[0][2]), spots[0][1],
                                 spots[0][2])
        self._label(cls, x, y, text, anchor)

    def place_near(self, cls: str, px: float, py: float, text: str,
                   marks: list[tuple]) -> None:
        """Label the point (px, py): right of it, above, below, left, then further above
        or below (see place)."""
        self.place(cls, text, [(px + 9, py + 5, "start"), (px, py - 11, "middle"),
                               (px, py + 22, "middle"), (px - 9, py + 5, "end"),
                               (px, py - 28, "middle"), (px, py + 39, "middle")], marks)

    def finish(self, marks: list[tuple]) -> None:
        """Place the band and reference labels, clear of the markers."""
        for cls, text, spots in self.pending:
            self.place(cls, text, spots, marks)
        self.pending = []

    def svg(self, kind: str, aria: str, body: list[str]) -> str:
        return (f'<svg class="chart {kind}" viewBox="0 0 {W} {self.height:.0f}" role="img" '
                f'aria-label="{esc(aria)}" xmlns="http://www.w3.org/2000/svg">'
                f'{"".join(self.back)}{"".join(body)}{"".join(self.labels)}</svg>')


def nested_sizes(series: list[list[tuple]]) -> list[list[float]]:
    """A marker scale per point, per series [[(px, py)]]: 1, except where points of
    several series land within 3 units of each other. There the earlier series' marker
    is drawn larger (1.45, 1.9, ...), so each later, smaller one sits inside it, ringed by
    the surface colour, and every series stays visible."""
    sizes = [[1.0] * len(pts) for pts in series]
    for k, pts in enumerate(series):
        for j, (x, y) in enumerate(pts):
            later = {m for m in range(k + 1, len(series))
                     if any(abs(x - a) < 3 and abs(y - b) < 3 for a, b in series[m])}
            sizes[k][j] = 1.0 + 0.45 * len(later)
    return sizes


def legend(items: list[tuple]) -> str:
    """An HTML legend: (k, shape, name, draws a line, on the right axis) per entry."""
    lis = []
    for k, shape, name, line, right in items:
        r = " r" if right else ""
        ln = f'<line class="xyl xk{k}{r}" x1="1" y1="7" x2="25" y2="7"/>' if line else ""
        mark = f'<path class="xym xk{k}{r}" d="{shape_path(shape, 13, 7)}"/>' if shape else ""
        chip = (f'<svg class="xychip xk{k}" width="26" height="14" viewBox="0 0 26 14" '
                f'aria-hidden="true">{ln}{mark}</svg>')
        tail = " <small>(right axis)</small>" if right else ""
        lis.append(f"<li>{chip}{esc(name)}{tail}</li>")
    return f'<ul class="legend xyleg">{"".join(lis)}</ul>'


def _range(vals: list[float], fmt) -> str:
    lo, hi = min(vals), max(vals)
    return fmt(lo) if lo == hi else f"{fmt(lo)} to {fmt(hi)}"


def refs_summary(chart: dict) -> str:
    parts = [f"{r['label']} at x = {plain(r['x'])}" if "x" in r
             else f"{r['label']} at y = {val(r['y'])}" for r in chart.get("refs", [])]
    return f" Reference lines: {'; '.join(parts)}." if parts else ""


def xy_html(chart: dict) -> str:
    """Series on two numeric axes; see Frame for the axes and study.schema._xy for the
    fields. A line or step series is drawn as a 2-unit line with a marker on each point,
    a points series as markers only; a point with lo/hi gets a whisker. Each series'
    last value is printed next to its last point."""
    unit, series = chart["unit"], chart["series"]
    dual = chart.get("y_axes") == "dual"
    unit2 = chart.get("y2_unit", unit)

    def on_right(s):
        return dual and s.get("axis") == "right"

    def ys_of(ss):
        return [p[k] for s in ss for p in s["points"] for k in ("y", "lo", "hi") if k in p]

    data_xs = [p["x"] for s in series for p in s["points"]]
    xs = data_xs + [r["x"] for r in chart.get("refs", []) if "x" in r]
    ys = (ys_of([s for s in series if not on_right(s)])
          + [b[k] for b in chart.get("bands", []) for k in ("y_lo", "y_hi")]
          + [r["y"] for r in chart.get("refs", []) if "y" in r])
    ys2 = ys_of([s for s in series if on_right(s)]) if dual else None
    f = Frame(chart, xs, ys, ys2, data_xs)

    sizes = nested_sizes([[(f.x(p["x"]), (f.y2 if on_right(s) else f.y)(p["y"]))
                           for p in s["points"]] for s in series])
    lines, whiskers, marks, ends, coords = [], [], [], [], []
    for k, s in enumerate(series):
        right = on_right(s)
        yf, u = (f.y2, unit2) if right else (f.y, unit)
        r = " r" if right else ""
        shape = SHAPES[k]
        pts = [(f.x(p["x"]), yf(p["y"]), p) for p in s["points"]]
        style = s.get("style", "line")
        if style != "points" and len(pts) > 1:
            (x0, y0, _), rest = pts[0], pts[1:]
            if style == "step":
                d = f"M{x0:.1f} {y0:.1f}" + "".join(f"H{x:.1f}V{y:.1f}" for x, y, _ in rest)
            else:
                d = f"M{x0:.1f} {y0:.1f}" + "".join(f"L{x:.1f} {y:.1f}" for x, y, _ in rest)
            lines.append(f'<path class="xyl xk{k}{r}" d="{d}"/>')
        for j, (px, py, p) in enumerate(pts):
            lohi = ""
            if "lo" in p or "hi" in p:
                lo, hi = p.get("lo", p["y"]), p.get("hi", p["y"])
                ylo, yhi = yf(lo), yf(hi)
                whiskers.append(f'<line class="xyw xk{k}{r}" x1="{px:.1f}" y1="{ylo:.1f}" '
                                f'x2="{px:.1f}" y2="{yhi:.1f}"/>')
                for wy in (ylo, yhi):
                    whiskers.append(f'<line class="xyw xk{k}{r}" x1="{px - 4:.1f}" '
                                    f'y1="{wy:.1f}" x2="{px + 4:.1f}" y2="{wy:.1f}"/>')
                lohi = f" ({val(lo)} to {val(hi)})"
            tip = f"{s['name']}: {plain(p['x'])} → {_with_unit(val(p['y']), u)}{lohi}"
            marks.append(f'<path class="xym xk{k}{r}" data-px="{px:.1f}" data-py="{py:.1f}" '
                         f'data-shape="{shape}" d="{shape_path(shape, px, py, sizes[k][j])}">'
                         f"<title>{esc(tip)}</title></path>")
            coords.append((px, py))
        px, py, p = pts[-1]
        if not any(t == val(p["y"]) and abs(x - px) < 4 and abs(y - py) < 4
                   for x, y, t in ends):  # two series ending on one point: one label
            ends.append((px, py, val(p["y"])))
    f.finish(coords)
    for px, py, text in ends:
        f.place_near("xyv", px, py, text, coords)

    summary = "; ".join(
        f"{s['name']}: {len(s['points'])} point{'s' if len(s['points']) != 1 else ''}, "
        f"x {_range([p['x'] for p in s['points']], plain)}, "
        f"y {_with_unit(_range([p['y'] for p in s['points']], val), unit2 if on_right(s) else unit)}"
        for s in series)
    t1 = f"{chart['y_label']} ({unit})" if unit else chart["y_label"]
    aria = (f"Line chart: {t1} against {chart['x_label']}"
            + (" (log scale)" if chart.get("x_log") else "") + f". {summary}."
            + refs_summary(chart)
            + "".join(f" Band: {b['label']}, {val(b['y_lo'])} to {val(b['y_hi'])}."
                      for b in chart.get("bands", [])))
    out = f.svg("xy", aria, lines + whiskers + marks)
    if len(series) >= 2:
        out += legend([(k, SHAPES[k], s["name"], s.get("style", "line") != "points",
                        on_right(s)) for k, s in enumerate(series)])
    return out + _note(chart)
