"""Validation of a study unit's content.json.

A unit renders to a page and a brief from this one file, so a malformed unit fails
here, naming the field, instead of producing a broken page.
"""

from __future__ import annotations

from study.text import wrap

ARTIFACT_LEVELS = ("context", "container", "component", "dynamic")
NODE_KINDS = ("person", "system", "external", "store", "focus")
CHART_TYPES = ("stacked_bars", "bars")
MAX_LABEL = 22
MAX_SUB = 60
SUB_LINE = 30  # the diagram wraps a node's sub text at this width ...
SUB_LINES = 2  # ... and has room for two lines
MAX_COL = 3
MAX_ROW = 3
MAX_ONE_LINE = 160
MAX_SHORT = 40  # a map node's label
MAX_TAKEAWAY = 200


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


def _chart(ch, where):
    """Chart dict: type, unit, bars/items, and for stacked_bars an optional bool
    `show_totals` (default false) that prints each bar's summed total at its end."""
    kind = _get(ch, "type", str, where)
    if kind not in CHART_TYPES:
        raise ContentError(f"{where}.chart type '{kind}' not in {CHART_TYPES}")
    _get(ch, "unit", str, where)
    if "show_totals" in ch and not isinstance(ch["show_totals"], bool):
        raise ContentError(f"{where}.show_totals: expected bool")
    if kind == "stacked_bars":
        for i, bar in enumerate(_items(ch, "bars", where, fields=("label",))):
            for j, seg in enumerate(_items(bar, "segments", f"{where}.bars[{i}]",
                                           fields=("name",))):
                _get(seg, "value", float, f"{where}.bars[{i}].segments[{j}]")
    else:
        for i, it in enumerate(_items(ch, "items", where, fields=("label",))):
            _get(it, "value", float, f"{where}.items[{i}]")


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
    _relationships(c, where)
