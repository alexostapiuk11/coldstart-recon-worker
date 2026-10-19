"""Validation of a study unit's content.json.

A unit renders to a page and a brief from this one file, so a malformed unit fails
here, naming the field, instead of producing a broken page.
"""

from __future__ import annotations

import math
import re

from study.text import SENTINELS, known_units, unknown_link_units, wrap

ARTIFACT_LEVELS = ("context", "container", "component", "dynamic")
NODE_KINDS = ("person", "system", "external", "store", "focus")
CHART_TYPES = ("stacked_bars", "bars", "interval", "percentiles", "xy", "scatter")
SERIES_STYLES = ("line", "points", "step")
MAX_SERIES = 6  # xy series and scatter groups: one colour and one marker shape each
# Marker shapes, in the order series and groups take them (study.xy draws them).
SHAPES = ("circle", "diamond", "square", "triangle", "triangle-down", "cross")
MAX_POINT_LABEL = 30
MAX_LABEL = 22
MAX_SUB = 60
SUB_LINE = 30  # the diagram wraps a node's sub text at this width ...
SUB_LINES = 2  # ... and has room for two lines
MAX_COL = 3
MAX_ROW = 3
MAX_ONE_LINE = 160
# `short`: a requirement's name on its card and in the map; a result's answer-strip chip.
# Decisions and concepts may still carry one (it is validated) but nothing shows it: the
# map labels them with their card titles.
MAX_SHORT = 40
MAX_TAKEAWAY = 200
MAX_ARITHMETIC = 220  # a result's "How it is computed" row
# Implementation flow steps (see _flow).
MAX_STEP_LABEL = 60
MAX_OUTPUT = 140
MAX_WHEN = 32
MAX_PHASE = 40
MAX_EVIDENCE_NOTE = 80
PHASED_STEPS = (5, 12)
MILESTONES = (2, 6)
SHA = re.compile(r"[0-9a-f]{7,40}")


class ContentError(ValueError):
    """A unit's content.json is malformed; the message names the field."""


def _get(d, key, kind, where):
    if not isinstance(d, dict) or key not in d:
        raise ContentError(f"{where}: missing '{key}'")
    v = d[key]
    ok = isinstance(v, kind) and not (kind is int and isinstance(v, bool))
    if kind is float:
        ok = isinstance(v, (int, float)) and not isinstance(v, bool)
    if not ok:
        raise ContentError(f"{where}.{key}: expected {kind.__name__}")
    return v


def _items(d, key, where, *, at_least=1, at_most=None, fields=()):
    items = _get(d, key, list, where)
    if len(items) < at_least or (at_most is not None and len(items) > at_most):
        bound = f"{at_least} to {at_most}" if at_most else f"at least {at_least}"
        raise ContentError(f"{where}.{key}: needs {bound} items, has {len(items)}")
    for i, it in enumerate(items):
        for f in fields:
            _get(it, f, str, f"{where}.{key}[{i}]")
    return items


def _opt_str(d, key, where, max_len=None):
    """An optional string field: absent is fine; present must be a non-empty str."""
    if key not in d:
        return None
    v = _get(d, key, str, where)
    if not v.strip():
        raise ContentError(f"{where}.{key} is empty")
    if max_len is not None and len(v) > max_len:
        raise ContentError(f"{where}.{key} longer than {max_len} characters")
    return v


def so_ids(result: dict) -> list[str]:
    """The decision ids a result supports: `so` may be one id or a list of ids."""
    so = result.get("so")
    if so is None:
        return []
    return [so] if isinstance(so, str) else list(so)


def _links(d, key, ref, known, kind, where):
    """A decision's `serves` or `uses` list: [{ref: <known id>, because: <text>}]."""
    for j, link in enumerate(_get(d, key, list, where)):
        w = f"{where}.{key}[{j}]"
        target = _get(link, ref, str, w)
        if target not in known:
            raise ContentError(f"{w}.{ref} '{target}' is not a {kind} id")
        if not _get(link, "because", str, w).strip():
            raise ContentError(f"{w}.because is empty")


def _relationships(c, where):
    """Ids and the links between requirements, decisions, concepts and results.

    Every field is checked when present. Once any requirement has an `id` the unit has
    opted in to traceability, and the links must be complete: every requirement has an
    id and is served by a decision (or says why not), every decision serves at least one
    requirement, and every result supports a decision (or says why not).
    """
    reqs = c.get("requirements", [])
    traced = any(isinstance(r, dict) and "id" in r for r in reqs)
    req_ids = []
    for i, r in enumerate(reqs):
        w = f"{where}.requirements[{i}]"
        if traced and "id" not in r:
            raise ContentError(f"{w}: missing 'id' (once one requirement has an id, "
                               "all need one)")
        rid = _opt_str(r, "id", w)
        if rid is not None:
            if rid in req_ids:
                raise ContentError(f"{w}: duplicate id '{rid}'")
            req_ids.append(rid)
        _opt_str(r, "short", w, MAX_SHORT)
        _opt_str(r, "unlinked_reason", w)

    concept_ids = set()
    for i, t in enumerate(c.get("concepts", [])):
        w = f"{where}.concepts[{i}]"
        cid = _opt_str(t, "id", w)
        if cid is not None:
            if cid in concept_ids:
                raise ContentError(f"{w}: duplicate id '{cid}'")
            concept_ids.add(cid)
        _opt_str(t, "short", w, MAX_SHORT)

    decision_ids = [d["id"] for d in c.get("decisions", [])]
    served = {}
    for i, d in enumerate(c.get("decisions", [])):
        w = f"{where}.decisions[{i}]"
        _opt_str(d, "short", w, MAX_SHORT)
        if traced:
            _items(d, "serves", w)
        if "serves" in d:
            _links(d, "serves", "req", set(req_ids), "requirement", w)
            for link in d["serves"]:
                served.setdefault(link["req"], []).append(d["id"])
        if "uses" in d:
            _links(d, "uses", "concept", concept_ids, "concept", w)

    for i, r in enumerate(reqs):
        if not traced:
            break
        w = f"{where}.requirements[{i}] '{r['id']}'"
        if r["id"] in served and "unlinked_reason" in r:
            raise ContentError(f"{w} has an unlinked_reason but is served by "
                               f"{', '.join(served[r['id']])}; drop one")
        if r["id"] not in served and "unlinked_reason" not in r:
            raise ContentError(f"{w}: no decision serves it; add it to a decision's "
                               "`serves` or give an unlinked_reason")

    for i, r in enumerate(c.get("results", [])):
        w = f"{where}.results[{i}]"
        _opt_str(r, "short", w, MAX_SHORT)
        _opt_str(r, "takeaway", w, MAX_TAKEAWAY)
        _opt_str(r, "so_none_reason", w)
        so = r.get("so")
        if so is not None:
            if not isinstance(so, (str, list)) or (
                    isinstance(so, list) and not all(isinstance(x, str) for x in so)):
                raise ContentError(f"{w}.so: expected a decision id or a list of them")
            for x in so_ids(r):
                if x not in decision_ids:
                    raise ContentError(f"{w}.so '{x}' is not a decision id")
        if so_ids(r) and "so_none_reason" in r:
            raise ContentError(f"{w} has both `so` and `so_none_reason`; keep one")
        if traced and not so_ids(r) and "so_none_reason" not in r:
            raise ContentError(f"{w}: needs `so` (the decision ids it supports) or a "
                               "so_none_reason")

    for i, s in enumerate(c.get("flow", [])):
        w = f"{where}.flow[{i}]"
        dec = _opt_str(s, "decision", w)
        if dec is not None and dec not in decision_ids:
            raise ContentError(f"{w}.decision '{dec}' is not a decision id")


def phased(c: dict) -> bool:
    """A unit opts in to the phased flow (timeline, milestones) once any step has a
    `phase` or a `milestone`."""
    return any(isinstance(s, dict) and ("phase" in s or "milestone" in s)
               for s in c.get("flow", []))


def flow_phases(flow: list) -> list[tuple[str, list[tuple[int, dict]]]]:
    """[(phase, [(step number, step), ...]), ...] in the order written; step numbers run
    on across phases from 1."""
    out = []
    for n, s in enumerate(flow, 1):
        if not out or out[-1][0] != s.get("phase"):
            out.append((s.get("phase"), []))
        out[-1][1].append((n, s))
    return out


def _flow_step(s, w):
    """One step's optional fields: phase, output, when, milestone, evidence. A milestone
    needs an output, a when and at least one evidence commit."""
    if len(_get(s, "label", str, w)) > MAX_STEP_LABEL:
        raise ContentError(f"{w}.label longer than {MAX_STEP_LABEL} characters")
    _opt_str(s, "phase", w, MAX_PHASE)
    _opt_str(s, "output", w, MAX_OUTPUT)
    _opt_str(s, "when", w, MAX_WHEN)
    if "milestone" in s:
        _get(s, "milestone", bool, w)
    if "evidence" in s:
        for j, e in enumerate(_items(s, "evidence", w)):
            we = f"{w}.evidence[{j}]"
            sha = _get(e, "commit", str, we)
            if not SHA.fullmatch(sha):
                raise ContentError(f"{we}.commit '{sha}' must be 7 to 40 hex characters "
                                   "(lower case)")
            _opt_str(e, "repo", we)
            _opt_str(e, "note", we, MAX_EVIDENCE_NOTE)
    if s.get("milestone"):
        for f in ("output", "when", "evidence"):
            if f not in s:
                raise ContentError(f"{w} '{s['label']}' is a milestone; it needs `{f}`")


def _flow(c, where):
    """Every step's fields; then, for an artifact whose flow is phased (see `phased`), the
    timeline's rules: 5 to 12 steps, 2 to 6 milestones, every step with a phase and an
    output, at least two phases, and each phase's steps consecutive (the page groups them
    in the order written)."""
    steps = c.get("flow", [])
    for i, s in enumerate(steps):
        _flow_step(s, f"{where}.flow[{i}]")
    if c["kind"] != "artifact" or not phased(c):
        return
    lo, hi = PHASED_STEPS
    if not lo <= len(steps) <= hi:
        raise ContentError(f"{where}.flow: a phased flow needs {lo} to {hi} steps, "
                           f"has {len(steps)}")
    for i, s in enumerate(steps):
        for f in ("phase", "output"):
            _get(s, f, str, f"{where}.flow[{i}]")
    lo, hi = MILESTONES
    n = sum(1 for s in steps if s.get("milestone"))
    if not lo <= n <= hi:
        raise ContentError(f"{where}.flow: needs {lo} to {hi} milestones, has {n}")
    order = []
    for i, s in enumerate(steps):
        if order and s["phase"] == order[-1]:
            continue
        if s["phase"] in order:
            raise ContentError(f"{where}.flow[{i}].phase '{s['phase']}' comes back after "
                               f"'{order[-1]}'; a phase's steps must be consecutive")
        order.append(s["phase"])
    if len(order) < 2:
        raise ContentError(f"{where}.flow: needs at least 2 phases, has {len(order)}")


def _chart(ch, where):
    """Chart dict: type, unit, then by type:

    - stacked_bars: bars of named segments, optional bool `show_totals` (default false)
      that prints each bar's summed total at its end, optional `deltas`
      ([{between, text}], what changed from one bar to another), `highlight` (segment
      names or merge labels drawn in colour; the rest go grey), `merge` (groups of
      segments drawn as one, see _merge) and `ghost` (a dashed outline on one bar of
      where a segment sat in another, see _ghost);
    - bars: items, one value each;
    - interval: rows of {label, estimate, low, high} (low <= estimate <= high), optional
      `zero_label`, `left_label`, `right_label`, `shade` ('left' or 'right' of zero) and
      `shade_caption` (the line under the axis explaining the shade); a row may set
      `decimals` (default: the most decimal places among its three values);
    - percentiles: rows of {label, values: [{name, value}], optional max_label}, on one
      shared axis from zero, optional `note` (see _percentile_rows);
    - xy: line, point or step series on two numeric axes (see _xy);
    - scatter: groups of points on two numeric axes, an optional frontier (see _scatter).
    """
    kind = _get(ch, "type", str, where)
    if kind not in CHART_TYPES:
        raise ContentError(f"{where}.chart type '{kind}' not in {CHART_TYPES}")
    _get(ch, "unit", str, where)
    if "show_totals" in ch and not isinstance(ch["show_totals"], bool):
        raise ContentError(f"{where}.show_totals: expected bool")
    for f in ("deltas", "highlight", "merge", "ghost"):
        if f in ch and kind != "stacked_bars":
            raise ContentError(f"{where}.{f}: only stacked_bars charts take {f}")
    if kind == "interval":
        for f in ("zero_label", "left_label", "right_label", "shade_caption"):
            _opt_str(ch, f, where)
        if ch.get("shade", "left") not in ("left", "right"):
            raise ContentError(f"{where}.shade must be 'left' or 'right'")
        for i, row in enumerate(_items(ch, "rows", where, fields=("label",))):
            w = f"{where}.rows[{i}]"
            low, est, high = (_get(row, f, float, w) for f in ("low", "estimate", "high"))
            if "decimals" in row and not 0 <= _get(row, "decimals", int, w) <= 6:
                raise ContentError(f"{w}.decimals must be 0 to 6")
            if not low <= est <= high:
                raise ContentError(f"{w} '{row['label']}': needs low <= estimate <= high, got "
                                   f"{low}, {est}, {high}")
    elif kind == "stacked_bars":
        names = set()
        for i, bar in enumerate(_items(ch, "bars", where, fields=("label",))):
            for j, seg in enumerate(_items(bar, "segments", f"{where}.bars[{i}]",
                                           fields=("name",))):
                _get(seg, "value", float, f"{where}.bars[{i}].segments[{j}]")
                names.add(seg["name"])
        deltas = _get(ch, "deltas", list, where) if "deltas" in ch else []
        for i, dl in enumerate(deltas):
            for f in ("between", "text"):
                if not _get(dl, f, str, f"{where}.deltas[{i}]").strip():
                    raise ContentError(f"{where}.deltas[{i}].{f} is empty")
        labels = _merge(ch, names, where)
        if "highlight" in ch:
            for name in _get(ch, "highlight", list, where):
                if name not in names | labels:
                    raise ContentError(f"{where}.highlight '{name}' is not a segment name")
        if "ghost" in ch:
            _ghost(ch, where)
    elif kind == "percentiles":
        _percentile_rows(ch, where)
    elif kind == "xy":
        _xy(ch, where)
    elif kind == "scatter":
        _scatter(ch, where)
    else:
        for i, it in enumerate(_items(ch, "items", where, fields=("label",))):
            _get(it, "value", float, f"{where}.items[{i}]")


def _merge(ch, names, where):
    """`merge`: [{names: [2+ segment names], label}]; a name joins at most one group.
    Returns the merge labels."""
    if "merge" not in ch:
        return set()
    merged, labels = set(), set()
    for i, g in enumerate(_get(ch, "merge", list, where)):
        w = f"{where}.merge[{i}]"
        for name in _items(g, "names", w, at_least=2):
            if name not in names:
                raise ContentError(f"{w}: '{name}' is not a segment name")
            if name in merged:
                raise ContentError(f"{w}: '{name}' is already merged in an earlier group")
            merged.add(name)
        if not _get(g, "label", str, w).strip():
            raise ContentError(f"{w}.label is empty")
        labels.add(g["label"])
    return labels


def _ghost(ch, where):
    """`ghost`: {segment, from_bar, on_bar}: two different bar labels, and a segment drawn
    in from_bar (a segment name, or a merge label)."""
    g = _get(ch, "ghost", dict, where)
    w = f"{where}.ghost"
    seg, src, dst = (_get(g, f, str, w) for f in ("segment", "from_bar", "on_bar"))
    bars = {b["label"]: b for b in ch["bars"]}
    for f, label in (("from_bar", src), ("on_bar", dst)):
        if label not in bars:
            raise ContentError(f"{w}.{f} '{label}' is not a bar label")
    if src == dst:
        raise ContentError(f"{w}: from_bar and on_bar must be two different bars")
    if seg not in [n for n, _, _ in merged_segments(ch, bars[src])]:
        raise ContentError(f"{w}.segment '{seg}' is not drawn in bar '{src}'")


def merged_segments(chart: dict, bar: dict) -> list[tuple[str, float, list]]:
    """A stacked bar's segments as drawn: (name, value, members). A `merge` group becomes
    one segment named by its label, at its first member's place, whose value is the sum
    of its members ([(name, value)], in bar order); other segments have no members."""
    group = {n: g["label"] for g in chart.get("merge", []) for n in g["names"]}
    out, at = [], {}
    for s in bar["segments"]:
        label = group.get(s["name"])
        if label is None:
            out.append((s["name"], s["value"], []))
        elif label in at:
            name, value, members = out[at[label]]
            out[at[label]] = (name, value + s["value"], members + [(s["name"], s["value"])])
        else:
            at[label] = len(out)
            out.append((label, s["value"], [(s["name"], s["value"])]))
    return out


def _percentile_rows(ch, where):
    """rows of {label, values: [{name, value}], optional max_label {text, value}}; values
    are non-negative (the axis starts at zero), names unique in a row, and a max_label
    lies at or past the row's highest percentile. Optional chart `note`."""
    _opt_str(ch, "note", where)
    for i, row in enumerate(_items(ch, "rows", where, fields=("label",))):
        w = f"{where}.rows[{i}]"
        names = set()
        for j, v in enumerate(_items(row, "values", w, fields=("name",))):
            wv = f"{w}.values[{j}]"
            if _get(v, "value", float, wv) < 0:
                raise ContentError(f"{wv}.value is negative; the axis starts at zero")
            if v["name"] in names:
                raise ContentError(f"{w}: duplicate percentile '{v['name']}'")
            names.add(v["name"])
        if "max_label" in row:
            m = _get(row, "max_label", dict, w)
            if not _get(m, "text", str, f"{w}.max_label").strip():
                raise ContentError(f"{w}.max_label.text is empty")
            top = max(v["value"] for v in row["values"])
            if _get(m, "value", float, f"{w}.max_label") < top:
                raise ContentError(f"{w}.max_label.value {m['value']} is below the row's "
                                   f"highest percentile {top}")


def _finite(d, key, where):
    v = _get(d, key, float, where)
    if not math.isfinite(v):
        raise ContentError(f"{where}.{key} must be a finite number")
    return v


def _label(d, key, where):
    if not _get(d, key, str, where).strip():
        raise ContentError(f"{where}.{key} is empty")


def _log_x(x, x_log, where):
    if x_log and x <= 0:
        raise ContentError(f"{where}.x is {x:g}; a log x axis needs every x > 0")


def _numeric_frame(ch, where):
    """Fields `xy` and `scatter` share: x_label, y_label, optional bools x_log and
    y_from_zero, optional `note`, and optional `refs` [{x or y: number, label}] (dashed
    reference lines). Returns x_log."""
    _label(ch, "x_label", where)
    _label(ch, "y_label", where)
    for f in ("x_log", "y_from_zero"):
        if f in ch:
            _get(ch, f, bool, where)
    x_log = ch.get("x_log", False)
    _opt_str(ch, "note", where)
    for i, r in enumerate(_get(ch, "refs", list, where) if "refs" in ch else []):
        w = f"{where}.refs[{i}]"
        axes = [k for k in ("x", "y") if isinstance(r, dict) and k in r]
        if len(axes) != 1:
            raise ContentError(f"{w}: needs exactly one of 'x' or 'y'")
        v = _finite(r, axes[0], w)
        if axes[0] == "x":
            _log_x(v, x_log, w)
        _label(r, "label", w)
    return x_log


def _xy(ch, where):
    """series: 1 to 6 of {name (unique), points: [{x, y, optional lo, hi}] with x sorted
    ascending (equal x allowed) and lo <= y <= hi, optional style 'line' | 'points' |
    'step' (default line), optional axis 'left' | 'right'}; optional `bands`
    [{y_lo < y_hi, label}] (on the left axis); optional y_axes 'single' | 'dual' (dual
    needs `y2_label`, optional `y2_unit`, and a series on each axis)."""
    x_log = _numeric_frame(ch, where)
    axes = ch.get("y_axes", "single")
    if axes not in ("single", "dual"):
        raise ContentError(f"{where}.y_axes must be 'single' or 'dual'")
    names, sides = set(), set()
    for i, s in enumerate(_items(ch, "series", where, at_most=MAX_SERIES, fields=("name",))):
        w = f"{where}.series[{i}]"
        _label(s, "name", w)
        if s["name"] in names:
            raise ContentError(f"{w}: duplicate series name '{s['name']}'")
        names.add(s["name"])
        if s.get("style", "line") not in SERIES_STYLES:
            raise ContentError(f"{w}.style '{s['style']}' not in {SERIES_STYLES}")
        side = s.get("axis", "left")
        if side not in ("left", "right"):
            raise ContentError(f"{w}.axis must be 'left' or 'right'")
        if side == "right" and axes != "dual":
            raise ContentError(f"{w}: the right axis needs y_axes 'dual'")
        sides.add(side)
        last = None
        for j, p in enumerate(_items(s, "points", w)):
            wp = f"{w}.points[{j}]"
            x, y = _finite(p, "x", wp), _finite(p, "y", wp)
            _log_x(x, x_log, wp)
            lo = _finite(p, "lo", wp) if "lo" in p else y
            hi = _finite(p, "hi", wp) if "hi" in p else y
            if not lo <= y <= hi:
                raise ContentError(f"{wp}: needs lo <= y <= hi, got {lo:g}, {y:g}, {hi:g}")
            if last is not None and x < last:
                raise ContentError(f"{w} '{s['name']}': x must be sorted ascending; "
                                   f"{x:g} comes after {last:g}")
            last = x
    if axes == "dual":
        _label(ch, "y2_label", where)
        _opt_str(ch, "y2_unit", where)
        if sides != {"left", "right"}:
            raise ContentError(f"{where}: a dual chart needs at least one series on each axis")
    else:
        for f in ("y2_label", "y2_unit"):
            if f in ch:
                raise ContentError(f"{where}.{f} needs y_axes 'dual'")
    for i, b in enumerate(_get(ch, "bands", list, where) if "bands" in ch else []):
        w = f"{where}.bands[{i}]"
        lo, hi = _finite(b, "y_lo", w), _finite(b, "y_hi", w)
        if not lo < hi:
            raise ContentError(f"{w}: needs y_lo < y_hi, got {lo:g}, {hi:g}")
        _label(b, "label", w)


def group_shapes(groups: list[dict]) -> list[str]:
    """Each scatter group's marker: its own `marker`, else the first shape in SHAPES that
    no group has taken."""
    taken = {g["marker"] for g in groups if g.get("marker")}
    free = iter(s for s in SHAPES if s not in taken)
    return [g.get("marker") or next(free) for g in groups]


def _scatter(ch, where):
    """groups: 1 to 6 of {name (unique), points: [{x, y, optional label}], optional
    marker (a shape in SHAPES, one group's only)}; optional frontier {name, points: 2+
    [{x, y}]} running down and to the right (lower-left is better): x rising strictly, y
    never rising."""
    x_log = _numeric_frame(ch, where)
    names, markers = set(), {}
    for i, g in enumerate(_items(ch, "groups", where, at_most=MAX_SERIES, fields=("name",))):
        w = f"{where}.groups[{i}]"
        _label(g, "name", w)
        if g["name"] in names:
            raise ContentError(f"{w}: duplicate group name '{g['name']}'")
        names.add(g["name"])
        if "marker" in g:
            m = _get(g, "marker", str, w)
            if m not in SHAPES:
                raise ContentError(f"{w}.marker '{m}' not in {SHAPES}")
            if m in markers:
                raise ContentError(f"{w}.marker '{m}' is already used by '{markers[m]}'")
            markers[m] = g["name"]
        for j, p in enumerate(_items(g, "points", w)):
            wp = f"{w}.points[{j}]"
            _log_x(_finite(p, "x", wp), x_log, wp)
            _finite(p, "y", wp)
            _opt_str(p, "label", wp, MAX_POINT_LABEL)
    if "frontier" in ch:
        fr = _get(ch, "frontier", dict, where)
        w = f"{where}.frontier"
        _label(fr, "name", w)
        if fr["name"] in names:
            raise ContentError(f"{w}.name '{fr['name']}' is also a group name")
        last = None
        for j, p in enumerate(_items(fr, "points", w, at_least=2)):
            wp = f"{w}.points[{j}]"
            x, y = _finite(p, "x", wp), _finite(p, "y", wp)
            _log_x(x, x_log, wp)
            if last and not (x > last[0] and y <= last[1]):
                raise ContentError(f"{w}: x must rise strictly and y never rise (lower-left "
                                   f"is better); point {j} is ({x:g}, {y:g}) after "
                                   f"({last[0]:g}, {last[1]:g})")
            last = (x, y)


def _view(v, where, allowed):
    for f in ("level", "title", "caption"):
        _get(v, f, str, where)
    if v["level"] not in allowed:
        raise ContentError(f"{where}.level '{v['level']}' not in {allowed}")
    nodes = _items(v, "nodes", where, at_least=2, fields=("id", "label"))
    ids, cells = set(), set()
    for i, n in enumerate(nodes):
        w = f"{where}.nodes[{i}]"
        if n["id"] in ids:
            raise ContentError(f"{w}: duplicate node id '{n['id']}'")
        ids.add(n["id"])
        if len(n["label"]) > MAX_LABEL:
            raise ContentError(f"{w}.label longer than {MAX_LABEL} characters")
        if len(n.get("sub", "")) > MAX_SUB:
            raise ContentError(f"{w}.sub longer than {MAX_SUB} characters")
        if len(wrap(n.get("sub", ""), SUB_LINE)) > SUB_LINES:
            raise ContentError(f"{w} '{n['label']}'.sub needs more than two lines of "
                               f"{SUB_LINE} characters; shorten it")
        if n.get("kind", "system") not in NODE_KINDS:
            raise ContentError(f"{w}.kind not in {NODE_KINDS}")
        col, row = _get(n, "col", int, w), _get(n, "row", int, w)
        if not (0 <= col <= MAX_COL and 0 <= row <= MAX_ROW):
            raise ContentError(f"{w}: col/row must be 0 to {MAX_COL}")
        if (col, row) in cells:
            raise ContentError(f"{w}: cell ({col}, {row}) already used")
        cells.add((col, row))
    for i, e in enumerate(v.get("edges", [])):
        for end in ("from", "to"):
            if _get(e, end, str, f"{where}.edges[{i}]") not in ids:
                raise ContentError(f"{where}.edges[{i}]: edge {end} is not a node id")


def _cross_page(c, where):
    """Optional `links` {unit: https URL} and `prereqs` [{unit, label}], and every
    [text](unit:concept) link in the content's strings naming a known unit."""
    if "links" in c:
        for unit, url in _get(c, "links", dict, where).items():
            if not isinstance(url, str) or not url.startswith("https://"):
                raise ContentError(f"{where}.links.{unit} must begin with https://")
    if "prereqs" in c:
        for i, p in enumerate(_items(c, "prereqs", where, fields=("unit", "label"))):
            if not p["label"].strip():
                raise ContentError(f"{where}.prereqs[{i}].label is empty")
    known = known_units(c)

    def walk(node, path):
        if isinstance(node, str):
            if any(ch in node for ch in SENTINELS):
                raise ContentError(f"{path}: contains a control character")
            for unit in unknown_link_units(node, known):
                raise ContentError(f"{path}: link to unknown unit '{unit}'; add it to "
                                   "`links` or `prereqs`")
        elif isinstance(node, dict):
            for k, v in node.items():
                if k not in ("sources", "links"):
                    walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk({k: v for k, v in c.items() if k != "id"}, where)


def validate(c: dict) -> None:
    """Raise ContentError if the unit cannot be rendered. Return None otherwise."""
    for f in ("id", "title"):
        _get(c, f, str, "unit")
    where = c["id"]
    kind = _get(c, "kind", str, where)
    if kind not in ("artifact", "prereq"):
        raise ContentError(f"{where}.kind must be 'artifact' or 'prereq'")
    if not 2 <= len(_get(c, "short_title", str, where).split()) <= 4:
        raise ContentError(f"{where}.short_title must be two to four words")
    _get(c, "minutes", int, where)
    for s in _items(c, "sources", where, fields=("file", "section")):
        del s
    _items(c, "recall", where, fields=("q", "a"))

    for i, d in enumerate(c.get("derived_numbers", [])):
        _get(d, "value", str, f"{where}.derived_numbers[{i}]")
        _get(d, "how", str, f"{where}.derived_numbers[{i}]")

    allowed = ARTIFACT_LEVELS if kind == "artifact" else ("concept",)
    for i, v in enumerate(c.get("views", [])):
        _view(v, f"{where}.views[{i}]", allowed)
    for i, t in enumerate(c.get("concepts", [])):
        _get(t, "term", str, f"{where}.concepts[{i}]")
        _get(t, "plain", str, f"{where}.concepts[{i}]")

    decision_ids = set()
    for i, d in enumerate(c.get("decisions", [])):
        for f in ("id", "title", "problem", "chosen", "why", "cost"):
            _get(d, f, str, f"{where}.decisions[{i}]")
        for f in ("why_short", "cost_short"):
            if len(_get(d, f, str, f"{where}.decisions[{i}]")) > MAX_ONE_LINE:
                raise ContentError(
                    f"{where}.decisions[{i}].{f} longer than {MAX_ONE_LINE} characters")
        _items(d, "options", f"{where}.decisions[{i}]", at_least=2)
        if d["id"] in decision_ids:
            raise ContentError(f"{where}.decisions[{i}]: duplicate id '{d['id']}'")
        decision_ids.add(d["id"])

    for i, r in enumerate(c.get("results", [])):
        w = f"{where}.results[{i}]"
        for f in ("title", "axis", "read_as"):
            _get(r, f, str, w)
        _opt_str(r, "arithmetic", w, MAX_ARITHMETIC)
        _chart(_get(r, "chart", dict, w), w)

    if kind == "artifact":
        _get(c, "question", str, where)
        _items(c, "requirements", where, at_least=3, fields=("text", "why"))
        levels = sorted(v["level"] for v in c.get("views", []))
        if levels != sorted(ARTIFACT_LEVELS):
            raise ContentError(f"{where}.views: levels must be exactly {ARTIFACT_LEVELS} "
                               f"once each, got {levels}")
        _items(c, "decisions", where, at_least=4, at_most=6)
        _items(c, "flow", where, at_least=3, fields=("label", "detail"))
        iv = _get(c, "interview", dict, where)
        for f in ("pitch30", "pitch120", "limits"):
            _get(iv, f, str, f"{where}.interview")
        _items(iv, "followups", f"{where}.interview", at_least=3, fields=("q", "a"))
    else:
        for i, t in enumerate(_items(c, "concepts", where, at_least=3)):
            _get(t, "analogy", str, f"{where}.concepts[{i}]")
            _get(t, "why", str, f"{where}.concepts[{i}]")
        _items(c, "used_by", where, at_least=1)
    _flow(c, where)
    _relationships(c, where)
    _cross_page(c, where)
