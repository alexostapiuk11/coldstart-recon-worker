"""Inline SVG for a sequence view: participants as boxes across the top, each with a
dashed lifeline down the page, and steps as rows stacked top to bottom.

A message is an arrow between two lifelines (or a loop back to its own), its label centred
above it; a reply is dashed; a fault (an injected kill or pause) is drawn in the warning
colour with a bolt. A crash puts an X on its lifeline, which is drawn as down (dotted, in
the warning colour) until the participant next acts. A note is a box over one or several
lifelines; a gap breaks every lifeline and says how much time passed. Marks: a duplicate
is drawn in red with a badge, a message never sent is dashed and ends in an X.

Steps are numbered in circles at the left margin; gaps are not numbered. The viewBox is
sized to the steps, so a long sequence grows down the page. A wide diagram cannot be read
on a narrow screen, so below the width where its labels would render under 12 px the SVG
gives way to a numbered text list of the same steps (a container query, see
study.page.seq_css), which states crash, gap and the marks in words.
"""

from __future__ import annotations

from study.schema import SEQ_MARKS
from study.text import esc, wrap

CH_L = 7.4  # width allowance per character: 13 px step labels
CH_T = 7.0  # 12 px italic text under an arrow, participant sub text
CH_B = 7.3  # 12 px bold badge words
CH_H = 8.6  # 14 px bold participant names
L = 44  # lifelines start right of the step-number column
TOP, HH = 8, 46  # header boxes: top, height
LINE = 15  # pitch of label lines
WRAP = 30  # message labels wrap at this many characters
NOTE_WRAP = 40
MIN_GAP = 120  # minimum distance between neighbouring lifelines
SELF_W = 30  # a self message's loop width
# Labels are 13 units: below this share of its natural width they would render under
# 12 px, and the page shows the text list instead.
MIN_SCALE = 12 / 13


def badge_word(step: dict) -> str:
    return step.get("badge") or SEQ_MARKS[step["mark"]]


def _ends(step: dict) -> tuple[str, str]:
    return step["from"], step.get("to", step["from"])


def _arrowish(step: dict) -> bool:
    return step.get("kind", "message") in ("message", "reply", "fault")


def _below(step: dict) -> tuple[float, float]:
    """(badge width, text width) of the line under an arrow."""
    bw = len(badge_word(step)) * CH_B + 14 if step.get("mark") else 0.0
    tw = len(step["text"]) * CH_T if step.get("text") else 0.0
    return bw, tw


def _columns(view: dict) -> tuple[list[float], list[float]]:
    """(lifeline x per participant, header box width per participant). Neighbouring
    lifelines sit far enough apart for their boxes, and every arrow is long enough for
    its label and the line under it."""
    ps = view["participants"]
    col = {p["id"]: i for i, p in enumerate(ps)}
    hw = [max(len(p["label"]) * CH_H, len(p.get("sub", "")) * CH_T, 90) + 20 for p in ps]
    gaps = [max(MIN_GAP, (hw[i] + hw[i + 1]) / 2 + 20) for i in range(len(ps) - 1)]
    spans = []
    for s in view["steps"]:
        if not _arrowish(s) or s["from"] == s["to"]:
            continue
        a, b = sorted((col[s["from"]], col[s["to"]]))
        bw, tw = _below(s)
        lw = max(len(line) for line in wrap(s["label"], WRAP)) * CH_L
        need = max(lw + (16 if s.get("kind") == "fault" else 0), bw + tw + (8 if bw and tw else 0))
        spans.append((b - a, a, b, need + 30))
    for _, a, b, need in sorted(spans):
        have = sum(gaps[a:b])
        if have < need:
            gaps[a:b] = [g + (need - have) / (b - a) for g in gaps[a:b]]
    xs = [L + hw[0] / 2 + 4]
    for g in gaps:
        xs.append(xs[-1] + g)
    return xs, hw


def _text(cls: str, x: float, y: float, text: str, anchor: str = "start") -> str:
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}"{a}>{esc(text)}</text>'


def _bolt(x: float, y: float) -> str:
    """A small lightning bolt whose top-left corner is (x, y)."""
    return (f'<path class="sqbolt" d="M{x + 6:.1f} {y:.1f}L{x:.1f} {y + 8:.1f}H{x + 4:.1f}'
            f'L{x + 2:.1f} {y + 14:.1f}L{x + 9:.1f} {y + 5:.1f}H{x + 5:.1f}L{x + 7:.1f} '
            f'{y:.1f}z"/>')


def _cross(cls: str, x: float, y: float, r: float, data: bool = False) -> str:
    d = (f"M{x - r:.1f} {y - r:.1f}L{x + r:.1f} {y + r:.1f}"
         f"M{x - r:.1f} {y + r:.1f}L{x + r:.1f} {y - r:.1f}")
    at = f' data-x="{x:.1f}" data-y="{y:.1f}"' if data else ""
    return f'<path class="{cls}"{at} d="{d}"/>'


def _subtract(pieces: list[tuple[float, float]], lo: float, hi: float):
    out = []
    for a, b in pieces:
        if hi <= a or lo >= b:
            out.append((a, b))
            continue
        if lo > a:
            out.append((a, lo))
        if hi < b:
            out.append((hi, b))
    return out


def step_line(step: dict, names: dict[str, str], arrow: str = "->") -> str:
    """One step in words, for the brief and the aria label: 'A -> B: label (text) [tag]'."""
    kind = step.get("kind", "message")
    text = f" ({step['text']})" if step.get("text") else ""
    if kind == "gap":
        return f"(gap: {step['label']})"
    if kind == "note":
        a, b = _ends(step)
        who = names[a] if a == b else f"{names[a]} to {names[b]}"
        return f"Note over {who}: {step['label']}{text}"
    if kind == "crash":
        return f"{names[step['from']]}: {step['label']}{text} [crash]"
    tags = "".join(f" [{t}]" for t in ((kind if kind != "message" else None),
                                       badge_word(step) if step.get("mark") else None) if t)
    return f"{names[step['from']]} {arrow} {names[step['to']]}: {step['label']}{text}{tags}"


def numbered(steps: list[dict]) -> list[int | None]:
    """Each step's number: 1, 2, ... in order, None for a gap."""
    out, n = [], 0
    for s in steps:
        if s.get("kind") == "gap":
            out.append(None)
        else:
            n += 1
            out.append(n)
    return out


def list_below(view: dict) -> float:
    """The container width (CSS px) below which the SVG's labels would render under
    12 px, so the page shows the text list instead (study.page.seq_css)."""
    return round(_geometry(view)[0] * MIN_SCALE)


def _geometry(view: dict):
    xs, hw = _columns(view)
    ps = view["participants"]
    col = {p["id"]: i for i, p in enumerate(ps)}
    names = {p["id"]: p["label"] for p in ps}
    back, body, labels = [], [], []
    right = xs[-1] + hw[-1] / 2 + 4  # the rightmost extent of anything drawn
    for p, x, w in zip(ps, xs, hw):
        kind = p.get("kind", "system")
        sub = p.get("sub")
        ty = TOP + (19 if sub else 28)
        back.append(f'<g class="sqp k-{kind}" data-id="{esc(p["id"])}" data-x="{x:.1f}">'
                    f'<rect class="sqbox" x="{x - w / 2:.1f}" y="{TOP}" width="{w:.1f}" '
                    f'height="{HH}" rx="8"/>{_text("sqh", x, ty, p["label"], "middle")}'
                    + (_text("sqsub", x, ty + 17, sub, "middle") if sub else "") + "</g>")

    y = TOP + HH + 18  # top of the first row
    nums = numbered(view["steps"])
    gaps, crashes, acts = [], {}, {p["id"]: [] for p in ps}
    for s, n in zip(view["steps"], nums):
        kind = s.get("kind", "message")
        mark = s.get("mark")
        cls = f"sq-{kind}" + (f" sq-{mark}" if mark else "")
        g = []
        if kind == "gap":
            ry, h = y + 15, 36
            gaps.append((y + 4, y + 26))
            for x in xs:
                g.append(f'<path class="sqbreak" d="M{x - 7:.1f} {y + 9:.1f}l14 -5'
                         f'M{x - 7:.1f} {y + 25:.1f}l14 -5"/>')
            mid = (L + right) / 2
            labels.append(_text("sqgap", mid, y + 19, s["label"], "middle"))
        elif kind == "note":
            a, b = sorted((col[s["from"]], col[s.get("to", s["from"])]))
            span = xs[b] - xs[a] + (60 if b > a else 0)
            chars = max(NOTE_WRAP, int((span - 20) / CH_L))  # a wide note wraps less
            lines = wrap(s["label"], chars)
            if s.get("text"):
                lines += wrap(s["text"], chars)
            tw = max(len(line) for line in lines) * CH_L + 20
            bw = max(tw, span)
            bx = max(L, (xs[a] + xs[b]) / 2 - bw / 2)
            right = max(right, bx + bw)
            bh = len(lines) * LINE + 10
            ry, h = y + bh / 2, bh + 12
            g.append(f'<rect class="sqnote" x="{bx:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                     f'height="{bh}" rx="4"/>')
            for i, line in enumerate(lines):
                labels.append(_text("sqlabel sqnotet", bx + bw / 2, y + 17 + i * LINE, line,
                                    "middle"))
        elif kind == "crash":
            x = xs[col[s["from"]]]
            lines = [s["label"]] + ([s["text"]] if s.get("text") else [])
            ry, h = y + 10, 14 + LINE * len(lines)
            crashes.setdefault(s["from"], []).append(ry)
            acts[s["from"]].append(ry)
            g.append(_cross("sqx", x, ry, 7, data=True))
            for i, line in enumerate(lines):
                labels.append(_text("sqcrash" if i == 0 else "sqtext", x + 14, ry + 5 + i * LINE,
                                    line))
                right = max(right, x + 14 + len(line) * CH_L)
        elif s["from"] == s["to"]:  # a self message: a loop to the right of the lifeline
            x = xs[col[s["from"]]]
            lines = wrap(s["label"], WRAP)
            bw, tw = _below(s)
            ry = y + 16  # number circles a row apart, as under a one-line message
            h = max(LINE * len(lines), 18) + (18 if bw or tw else 0) + 28
            acts[s["from"]].append(ry)
            g.append(f'<path class="sqa sqself{_mark_cls(s)}" d="M{x:.1f} {ry:.1f}h{SELF_W}'
                     f'v14h-{SELF_W - 4}" marker-end="url(#{_marker(s)})"/>')
            for i, line in enumerate(lines):
                labels.append(_text("sqlabel", x + SELF_W + 8, ry + 9 + i * LINE, line))
                right = max(right, x + SELF_W + 8 + len(line) * CH_L)
            right = max(right, _under(labels, s, x + SELF_W + 8, ry + 9 + len(lines) * LINE + 4,
                                      "start"))
        else:
            xa, xb = xs[col[s["from"]]], xs[col[s["to"]]]
            lines = wrap(s["label"], WRAP)
            bw, tw = _below(s)
            ry = y + LINE * len(lines) + 4
            h = LINE * len(lines) + 4 + (22 if bw or tw else 0) + 14
            if s.get("mark") not in ("never_sent", "lost"):  # a crashed sender stays down
                acts[s["from"]].append(ry)
                acts[s["to"]].append(ry)
            d = 1 if xb > xa else -1
            end = xb - d * (2 if s.get("mark") in ("never_sent", "lost") else 6)
            x1 = xa + d * (12 if kind == "fault" else 0)
            arrow = f"sqa sq{kind}{_mark_cls(s)}" if kind != "message" else f"sqa{_mark_cls(s)}"
            if s.get("mark") in ("never_sent", "lost"):
                end = xa + (xb - xa) * 0.72
                g.append(f'<line class="{arrow}" x1="{x1:.1f}" y1="{ry:.1f}" x2="{end:.1f}" '
                         f'y2="{ry:.1f}"/>')
                g.append(_cross("sqnsx", end, ry, 6))
            else:
                g.append(f'<line class="{arrow}" x1="{x1:.1f}" y1="{ry:.1f}" x2="{end:.1f}" '
                         f'y2="{ry:.1f}" marker-end="url(#{_marker(s)})"/>')
            if kind == "fault":
                g.append(_bolt(xa + d * 2 - (9 if d < 0 else 0), ry - 7))
            mx = (xa + xb) / 2
            for i, line in enumerate(lines):
                labels.append(_text("sqlabel", mx, y + 12 + i * LINE, line, "middle"))
            _under(labels, s, mx, ry + 19, "middle")
        if n is not None:
            g.append(f'<circle class="sqnum" cx="{L / 2 - 4:.1f}" cy="{ry:.1f}" r="10"/>')
            labels.append(_text("sqn", L / 2 - 4, ry + 4, str(n), "middle"))
        body.append(f'<g class="sqs {cls}" data-n="{n or ""}" data-y="{ry:.1f}">'
                    + "".join(g) + "</g>")
        y += h
    bottom = y + 4
    width = right + 12

    lifelines = []
    for p, x in zip(ps, xs):
        pieces = [(TOP + HH, bottom)]
        for lo, hi in gaps:
            pieces = _subtract(pieces, lo, hi)
        down = []
        for cy in crashes.get(p["id"], []):
            later = [a for a in acts[p["id"]] if a > cy + 0.5]
            nxt = min(later) if later else bottom
            down += [(max(a, cy), min(b, nxt)) for a, b in pieces if a < nxt and b > cy]
        live = pieces
        for lo, hi in down:
            live = _subtract(live, lo, hi)
        for cls, segs in (("sqlife", live), ("sqlife sqdown", down)):
            for a, b in sorted(segs):
                if b - a > 0.5:
                    lifelines.append(f'<line class="{cls}" data-p="{esc(p["id"])}" '
                                     f'x1="{x:.1f}" y1="{a:.1f}" x2="{x:.1f}" y2="{b:.1f}"/>')
    return width, bottom, lifelines + back, body, labels, names


def _mark_cls(step: dict) -> str:
    return {"duplicate": " sqdup", "never_sent": " sqns", "lost": " sqns"}.get(
        step.get("mark"), "")


def _marker(step: dict) -> str:
    """The arrowhead's id suffix; the caller prefixes it with the diagram's uid."""
    if step.get("mark") == "duplicate":
        return "{uid}-dup"
    return "{uid}-" + {"reply": "open", "fault": "fault"}.get(step.get("kind", "message"), "solid")


def _under(labels: list[str], step: dict, x: float, y: float, anchor: str) -> float:
    """Draw the badge and the text under an arrow (centred on x, or starting at it);
    returns the right edge."""
    bw, tw = _below(step)
    if not bw and not tw:
        return x
    total = bw + tw + (8 if bw and tw else 0)
    left = x - total / 2 if anchor == "middle" else x
    if bw:
        cls = "sqbadge sqbadge-dup" if step["mark"] == "duplicate" else "sqbadge"
        labels.append(f'<rect class="{cls}" x="{left:.1f}" y="{y - 12:.1f}" width="{bw:.1f}" '
                      'height="16" rx="8"/>')
        labels.append(_text("sqbt", left + bw / 2, y, badge_word(step), "middle"))
    if tw:
        labels.append(_text("sqtext", left + total - tw, y, step["text"]))
    return left + total


LEGEND = (("reply", "dashed arrow: a reply"),
          ("fault", "orange arrow with a bolt: an injected fault"),
          ("crash", "X on a lifeline: a crash; dotted after it: down"),
          ("gap", "// across the lifelines: time passes"),
          ("duplicate", "red: applied a second time"),
          ("never_sent", "arrow ending in an X: never sent"),
          ("lost", "arrow ending in an X: never sent"))


def legend_text(view: dict) -> str:
    seen = {s.get("kind", "message") for s in view["steps"]} | {
        s["mark"] for s in view["steps"] if s.get("mark")}
    parts = ["solid arrow: a message"] + [t for k, t in LEGEND if k in seen]
    return " · ".join(dict.fromkeys(parts))


def sequence_html(view: dict, uid: str) -> str:
    width, height, back, body, labels, names = _geometry(view)
    u = esc(uid)
    defs = "".join(
        f'<marker id="{u}-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        f'markerHeight="7" orient="auto-start-reverse"><path d="{d}" class="sqah {c}"/></marker>'
        for k, d, c in (("solid", "M0,0 L10,5 L0,10 z", "sqah-solid"),
                        ("open", "M0,0 L10,5 L0,10", "sqah-open"),
                        ("fault", "M0,0 L10,5 L0,10 z", "sqah-fault"),
                        ("dup", "M0,0 L10,5 L0,10 z", "sqah-dup")))
    steps = "; ".join(f"{n}. {step_line(s, names)}" if n else step_line(s, names)
                      for s, n in zip(view["steps"], numbered(view["steps"])))
    aria = f"Sequence: {view['title']}. {steps}"
    svg = (f'<svg class="sqd" viewBox="0 0 {width:.0f} {height:.0f}" '
           f'style="max-width:{width * 1.25:.0f}px" role="img" aria-label="{esc(aria)}" '
           f'xmlns="http://www.w3.org/2000/svg"><defs>{defs}</defs>{"".join(back)}'
           + "".join(body).replace("{uid}", u) + "".join(labels) + "</svg>")

    items = []
    for p in view["participants"]:
        sub = f" — {esc(p['sub'])}" if p.get("sub") else ""
        kind = p.get("kind", "system")
        name = (f"<strong>{esc(p['label'])}</strong>" if kind == "focus"
                else esc(p["label"]) + (" <small>(external)</small>" if kind == "external"
                                        else ""))
        items.append(f"<li>{name}{sub}</li>")
    steps_html = []
    for s, n in zip(view["steps"], numbered(view["steps"])):
        kind = s.get("kind", "message")
        text = f" <small>({esc(s['text'])})</small>" if s.get("text") else ""
        if kind == "gap":
            steps_html.append(f'<li class="sq-gapi"><em>gap: {esc(s["label"])}</em></li>')
            continue
        if kind == "note":
            a, b = _ends(s)
            who = esc(names[a]) if a == b else f"{esc(names[a])} to {esc(names[b])}"
            line = f'<span class="sqw">note</span> {who}: {esc(s["label"])}{text}'
        elif kind == "crash":
            line = (f'<b class="sqw sqw-bad">crash</b> {esc(names[s["from"]])}: '
                    f'{esc(s["label"])}{text}')
        else:
            pre = {"fault": '<b class="sqw sqw-bad">fault</b> ',
                   "reply": '<span class="sqw">reply</span> '}.get(kind, "")
            mark = (f' <b class="sqw sqw-bad">{esc(badge_word(s))}</b>' if s.get("mark")
                    else "")
            line = (f"{pre}{esc(names[s['from']])} → {esc(names[s['to']])}: "
                    f"{esc(s['label'])}{text}{mark}")
        steps_html.append(f'<li value="{n}">{line}</li>')
    text_list = (f'<div class="sq-text"><ul>{"".join(items)}</ul>'
                 f'<ol class="sq-steps">{"".join(steps_html)}</ol></div>')
    legend = f'<p class="dlegend sqleg">{esc(legend_text(view))}</p>'
    return f'<div class="sq" id="sq-{u}">{svg}{legend}{text_list}</div>'
