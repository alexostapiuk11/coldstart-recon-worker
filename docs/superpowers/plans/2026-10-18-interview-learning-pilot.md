# Interview Learning Resources: Pilot (P1 + A1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared study-page builder and produce the pilot units, P1 ("LLM serving on a GPU") and A1 (cold start), each as a visual `page.html` plus a pasteable `brief.md`, so the owner can approve the format before the other six units are made.

**Architecture:** One `content.json` per unit is the single source of truth. A small stdlib-only package `study/` validates it and renders both the page (inline SVG C4 views and charts, decision cards, reveal-to-answer recall, no external assets) and the chat brief (markdown ending in the interview-mode prompt), so page and brief cannot drift. Tests check that the build is in sync, that every number in a unit's text is traceable to its cited source files, and that every cited section exists. UI boundary: none (no Shadow DOM or iframe); styles are one inline `<style>` in each page. No visible UI is removed: the existing explainers stay untouched and remain available; the new pages are an additional study path.

**Tech Stack:** Python 3.13 stdlib only (`html`, `json`, `re`), pytest, ruff, inline SVG/CSS/vanilla JS, Playwright MCP (or the built-in browser) for visual checks.

**Spec:** `docs/superpowers/specs/2026-10-18-interview-learning-resources-design.md`

**Standing rules (from the owner's CLAUDE.md and memory):**
- Run Python as `.venv/bin/python ...`. Never `uv run` in this repo (it re-syncs `.venv` and broke published-figure tests).
- Do not stage or edit `docs/learning/plan.md`, `docs/learning/progress.md` or `docs/superpowers/plans/2026-10-08-artifact-3-plan-2-pilot-and-preregistration.md`: other sessions have uncommitted work in them. Stage files by explicit path, never `git add -A`.
- Do not touch `.claude/` or `.playwright-mcp/` contents in commits.
- UI work: invoke `superpowers:verifying-visual-output` before claiming a page is done. DOM presence is not evidence; look at screenshots at desktop (1280 px) and phone (375 px).
- Before claiming anything passes, show the fresh test and ruff output in the same message.
- Every fact on a page comes from a source read in this task. If a seed fact below disagrees with the source, the source wins and the discrepancy is reported in the task's closing note.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

---

## File structure

| Path | Responsibility |
|---|---|
| `study/__init__.py` | Package marker; docstring states the boundary (imports nothing from other repo packages). |
| `study/schema.py` | `validate(content)`; raises `ContentError` naming the field. |
| `study/svg.py` | `diagram_svg`, `chart_html`: pure functions from view/chart dicts to HTML strings. |
| `study/text.py` | `esc`, `inline` (escape plus `**bold**` and `` `code` ``). |
| `study/brief.py` | `render_brief(content)` and the interview-mode prompt text. |
| `study/page.py` | `render_page(content)`: the HTML shell, CSS, JS, sections. |
| `study/trace.py` | `untraced_numbers`, `missing_sections`: source-traceability checks. |
| `study/build.py` | `STUDY_DIR`, `build_unit(dir)` returning `(page, brief)`. |
| `scripts/build_study.py` | CLI: writes `page.html` and `brief.md` for the named (or all) units. |
| `tests/study_examples.py` | Example content dicts for tests (not a test module). |
| `tests/test_study_schema.py`, `test_study_render.py`, `test_study_units.py` | Tests. |
| `docs/learning/study/README.md` | Index: units, how to study, how to use a brief in chat, published URLs. |
| `docs/learning/study/inventory-a1-explainer.md` | Task 1's capability inventory of the existing A1 explainer and keep/drop log. |
| `docs/learning/study/<unit>/content.json, page.html, brief.md` | A unit's source and outputs; units `p1`, `a1` in the pilot. |

---

### Task 1: Inventory and baseline of the existing A1 explainer

This work adds a new study path next to `explainer/page.html`. It does not delete or edit the old page, but the owner is told the new path replaces the old one for studying, so what the old page does is inventoried first and every capability gets a keep/drop decision.

**Files:**
- Read: `explainer/page.html`, `explainer/terms.json`, `explainer/numbers.json`, `scripts/build_explainer.py`
- Create: `docs/learning/study/inventory-a1-explainer.md`
- Create (baseline screenshots, scratch): `build/study-baseline/explainer-a1-desktop.png`, `explainer-a1-phone.png`

- [ ] **Step 1: Read the existing page's code and list what it does**

Read `explainer/page.html` and `scripts/build_explainer.py` in full (the page is ~55 KB; read in chunks). List every capability: each module or section, each interactive widget (e.g. the ECDF/resample frames, any prediction prompts, term tooltips, the tutor, checkpoints), each chart, navigation, and anything stored. Do not rely on the plan in `docs/learning/plan.md`.

- [ ] **Step 2: Capture the baseline**

Serve the repo root with the existing preview config (`mcp__Claude_Browser__preview_start` with name `post-preview`, port 8765, serves the repo root), open `http://127.0.0.1:8765/explainer/page.html`, and take screenshots at 1280 px wide and 375 px wide. Save to `build/study-baseline/` (gitignored scratch under `build/`; check with `git check-ignore build/study-baseline` and, if not ignored, leave the files uncommitted).

- [ ] **Step 3: Write the keep/drop log**

Create `docs/learning/study/inventory-a1-explainer.md` with a table: capability | where in old page | decision | reason. Decision is `Preserved in new A1 page (section X)`, `Preserved in P1`, or `Intentionally not carried over (reason; old page still available)`. Every inventoried capability appears in exactly one row. Expected drops to confirm by reading, not assume: the interactive resampling/ECDF widgets, the in-page tutor, per-module checkpoints, and the long jargon contract. End the file with a line: "Observable drops need the owner's sign-off at the pilot review gate (Task 10)."

- [ ] **Step 4: Commit**

```bash
git add docs/learning/study/inventory-a1-explainer.md
git commit -m "docs: inventory of artifact 1's explainer with keep/drop log for the new study path

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Content schema and validator

**Files:**
- Create: `study/__init__.py`, `study/schema.py`
- Create: `tests/study_examples.py`, `tests/test_study_schema.py`

- [ ] **Step 1: Write the example content and the failing tests**

`tests/study_examples.py`:

```python
"""Example study-unit content for the study package's tests.

Not a test module. The facts are invented; only the shape matters.
"""

import copy


def _view(level: str) -> dict:
    return {
        "level": level,
        "title": f"The {level} view",
        "caption": f"What the {level} view shows.",
        "nodes": [
            {"id": "a", "label": "Author", "sub": "runs the study", "kind": "person",
             "col": 0, "row": 0},
            {"id": "b", "label": "Harness", "sub": "schedules and records", "kind": "focus",
             "col": 1, "row": 0},
            {"id": "c", "label": "GPU worker", "kind": "external", "col": 2, "row": 0},
        ],
        "edges": [
            {"from": "a", "to": "b", "label": "starts"},
            {"from": "b", "to": "c", "label": "submits 3 jobs"},
        ],
    }


def artifact_unit() -> dict:
    return copy.deepcopy({
        "id": "x1",
        "kind": "artifact",
        "title": "Example artifact",
        "short_title": "Example Artifact",
        "minutes": 45,
        "question": "Does the example hold?",
        "requirements": [
            {"text": f"Requirement {i}", "why": f"Because {i}."} for i in range(3)
        ],
        "concepts": [{"term": "Term", "plain": "A plain definition."}],
        "views": [_view(lv) for lv in ("context", "container", "component", "dynamic")],
        "decisions": [
            {
                "id": f"d{i}",
                "title": f"Decision {i}",
                "problem": "A problem.",
                "options": ["Option one", "Option two"],
                "chosen": "Option one",
                "why": "A reason.",
                "cost": "A cost.",
            }
            for i in range(4)
        ],
        "flow": [{"label": f"Step {i}", "detail": f"Detail {i}."} for i in range(3)],
        "results": [
            {
                "title": "A result",
                "chart": {
                    "type": "stacked_bars",
                    "unit": "s",
                    "bars": [
                        {"label": "A", "segments": [
                            {"name": "load", "value": 40.5}, {"name": "compile", "value": 19.0}]},
                        {"label": "C", "segments": [
                            {"name": "load", "value": 21.3}, {"name": "compile", "value": 0.3}]},
                    ],
                },
                "axis": "Seconds to ready.",
                "read_as": "Shorter is faster.",
                "so": "d0",
            }
        ],
        "interview": {
            "pitch30": "Thirty seconds.",
            "pitch120": "Two minutes.",
            "followups": [{"q": f"Question {i}?", "a": f"Answer {i}."} for i in range(3)],
            "limits": "What it cannot claim.",
        },
        "recall": [{"q": "Why?", "a": "Because."}],
        "sources": [{"file": "docs/post.md", "section": "Where a vLLM cold start actually goes"}],
        "derived_numbers": [],
    })


def prereq_unit() -> dict:
    return copy.deepcopy({
        "id": "px",
        "kind": "prereq",
        "title": "Example prerequisite",
        "short_title": "Example Prerequisite",
        "minutes": 20,
        "used_by": ["a1"],
        "concepts": [
            {"term": f"Term {i}", "plain": "Plain.", "analogy": "Like a thing.",
             "why": "It matters."}
            for i in range(3)
        ],
        "views": [dict(_view("concept"), level="concept")],
        "recall": [{"q": "Why?", "a": "Because."}],
        "sources": [{"file": "docs/post.md", "section": "Where a vLLM cold start actually goes"}],
        "derived_numbers": [],
    })
```

`tests/test_study_schema.py`:

```python
import pytest

from study.schema import ContentError, validate
from tests.study_examples import artifact_unit, prereq_unit


def test_valid_units_pass():
    validate(artifact_unit())
    validate(prereq_unit())


def _fails(unit, match):
    with pytest.raises(ContentError, match=match):
        validate(unit)


def test_missing_field_is_named():
    u = artifact_unit()
    del u["question"]
    _fails(u, "question")


def test_artifact_needs_all_four_levels_once():
    u = artifact_unit()
    u["views"] = u["views"][:3]
    _fails(u, "levels")
    u = artifact_unit()
    u["views"][3]["level"] = "context"
    _fails(u, "levels")


def test_decision_count_is_four_to_six():
    u = artifact_unit()
    u["decisions"] = u["decisions"][:3]
    _fails(u, "decisions")
    u = artifact_unit()
    u["decisions"] = u["decisions"] * 2
    _fails(u, "decisions")


def test_duplicate_decision_ids_fail():
    u = artifact_unit()
    u["decisions"][1]["id"] = "d0"
    _fails(u, "duplicate")


def test_result_must_point_at_a_real_decision():
    u = artifact_unit()
    u["results"][0]["so"] = "nope"
    _fails(u, "so")


def test_edge_to_unknown_node_fails():
    u = artifact_unit()
    u["views"][0]["edges"][0]["to"] = "zzz"
    _fails(u, "edge")


def test_node_label_and_sub_length_are_bounded():
    u = artifact_unit()
    u["views"][0]["nodes"][0]["label"] = "x" * 23
    _fails(u, "label")
    u = artifact_unit()
    u["views"][0]["nodes"][0]["sub"] = "x" * 61
    _fails(u, "sub")


def test_two_nodes_cannot_share_a_cell():
    u = artifact_unit()
    u["views"][0]["nodes"][1].update(col=0, row=0)
    _fails(u, "cell")


def test_short_title_is_two_to_four_words():
    u = artifact_unit()
    u["short_title"] = "Solo"
    _fails(u, "short_title")


def test_chart_type_and_numbers_are_checked():
    u = artifact_unit()
    u["results"][0]["chart"]["type"] = "pie"
    _fails(u, "chart")
    u = artifact_unit()
    u["results"][0]["chart"]["bars"][0]["segments"][0]["value"] = "forty"
    _fails(u, "value")


def test_prereq_needs_three_concepts_with_analogy():
    u = prereq_unit()
    u["concepts"] = u["concepts"][:2]
    _fails(u, "concepts")
    u = prereq_unit()
    del u["concepts"][0]["analogy"]
    _fails(u, "analogy")


def test_sources_and_recall_are_required():
    u = artifact_unit()
    u["sources"] = []
    _fails(u, "sources")
    u = artifact_unit()
    u["recall"] = []
    _fails(u, "recall")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_study_schema.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'study'`.

- [ ] **Step 3: Implement**

`study/__init__.py`:

```python
"""Builds the interview study pages and chat briefs from content.json files.

Boundary: stdlib only. Nothing here imports another package in this repository.
"""
```

`study/schema.py`:

```python
"""Validation of a study unit's content.json.

A unit renders to a page and a brief from this one file, so a malformed unit fails
here, naming the field, instead of producing a broken page.
"""

from __future__ import annotations

ARTIFACT_LEVELS = ("context", "container", "component", "dynamic")
NODE_KINDS = ("person", "system", "external", "store", "focus")
CHART_TYPES = ("stacked_bars", "bars")
MAX_LABEL = 22
MAX_SUB = 60
MAX_COL = 3
MAX_ROW = 3


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


def _chart(ch, where):
    kind = _get(ch, "type", str, where)
    if kind not in CHART_TYPES:
        raise ContentError(f"{where}.chart type '{kind}' not in {CHART_TYPES}")
    _get(ch, "unit", str, where)
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
        _items(d, "options", f"{where}.decisions[{i}]", at_least=2)
        if d["id"] in decision_ids:
            raise ContentError(f"{where}.decisions[{i}]: duplicate id '{d['id']}'")
        decision_ids.add(d["id"])

    for i, r in enumerate(c.get("results", [])):
        w = f"{where}.results[{i}]"
        for f in ("title", "axis", "read_as"):
            _get(r, f, str, w)
        _chart(_get(r, "chart", dict, w), w)
        if "so" in r and r["so"] not in decision_ids:
            raise ContentError(f"{w}.so '{r['so']}' is not a decision id")

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
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_study_schema.py -v && .venv/bin/ruff check study tests/study_examples.py tests/test_study_schema.py`
Expected: 13 passed; `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add study/__init__.py study/schema.py tests/study_examples.py tests/test_study_schema.py
git commit -m "feat: study content schema and validator

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Text helpers and the SVG diagram and chart renderers

**Files:**
- Create: `study/text.py`, `study/svg.py`
- Create: `tests/test_study_render.py` (this task adds the first half; Tasks 4 and 5 append)

- [ ] **Step 1: Write the failing tests**

`tests/test_study_render.py`:

```python
import re

from study.svg import chart_html, diagram_html
from study.text import esc, inline
from tests.study_examples import artifact_unit


def test_esc_escapes_html():
    assert esc('<b>"x"</b> & y') == "&lt;b&gt;&quot;x&quot;&lt;/b&gt; &amp; y"


def test_inline_bold_and_code_after_escaping():
    assert inline("a **b** `c<d>`") == "a <strong>b</strong> <code>c&lt;d&gt;</code>"
    assert "<script>" not in inline("**<script>**")


def test_diagram_has_every_node_and_edge_label_and_unique_marker():
    view = artifact_unit()["views"][0]
    out = diagram_html(view, "x1-context")
    for n in view["nodes"]:
        assert n["label"] in out
    assert "submits 3 jobs" in out
    assert 'id="arr-x1-context"' in out
    assert out.count("<svg") == 1


def test_diagram_gives_phone_a_text_alternative():
    out = diagram_html(artifact_unit()["views"][0], "u")
    assert 'class="diagram-text"' in out
    assert "Author" in out.split('class="diagram-text"')[1]
    assert "→" in out.split('class="diagram-text"')[1]


def test_diagram_edges_stop_at_box_borders():
    # Two boxes in one row: the first edge must start right of box 0 and end left of box 1.
    out = diagram_html(artifact_unit()["views"][0], "u")
    line = re.search(r'<line class="edge" x1="([\d.]+)" y1="[\d.]+" x2="([\d.]+)"', out)
    x1, x2 = float(line.group(1)), float(line.group(2))
    assert 24 + 170 <= x1 < x2 <= 24 + 170 + 50 + 2


def test_stacked_chart_scales_segments_and_lists_a_legend():
    chart = artifact_unit()["results"][0]["chart"]
    out = chart_html(chart, "r0")
    assert out.count("<rect") >= 4  # four segments
    assert "load" in out and "compile" in out  # legend
    assert "59.5" in out  # first bar's total, shown at its end
    widths = [float(w) for w in re.findall(r'class="seg s\d" [^>]*width="([\d.]+)"', out)]
    assert widths[0] > widths[1] > widths[3]  # 40.5 > 19.0 > 0.3, proportional


def test_simple_bars_chart():
    chart = {"type": "bars", "unit": "tokens",
             "items": [{"label": "cold", "value": 35792}, {"label": "warm", "value": 43040}]}
    out = chart_html(chart, "r1")
    assert "35,792" in out and "43,040" in out
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_study_render.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'study.svg'`.

- [ ] **Step 3: Implement**

`study/text.py`:

```python
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
```

`study/svg.py`:

```python
"""Inline SVG for C4 views and charts. Pure functions from content dicts to HTML.

Diagrams are a grid: each node names a column and row, and edges are straight lines
clipped to the box borders. On phones the SVG is hidden by CSS and a text list of the
same nodes and edges is shown instead, because a 4-column diagram scaled to 375 px is
unreadable.
"""

from __future__ import annotations

from study.text import esc

W, H, GX, GY, PAD = 170, 72, 50, 44, 24


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
    width = PAD * 2 + cols * W + (cols - 1) * GX
    height = PAD * 2 + rows * H + (rows - 1) * GY

    def center(n):
        return PAD + n["col"] * (W + GX) + W / 2, PAD + n["row"] * (H + GY) + H / 2

    head = (f'<svg class="diagram" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{esc(view["title"])}" xmlns="http://www.w3.org/2000/svg">')
    marker = (f'<defs><marker id="arr-{esc(uid)}" viewBox="0 0 10 10" refX="9" refY="5" '
              'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
              '<path d="M0,0 L10,5 L0,10 z" class="arrow"/></marker></defs>')
    p = [head, marker]
    for e in view.get("edges", []):
        (ax, ay), (bx, by) = center(nodes[e["from"]]), center(nodes[e["to"]])
        x1, y1 = _clip(ax, ay, bx, by, W / 2 + 2, H / 2 + 2)
        x2, y2 = _clip(bx, by, ax, ay, W / 2 + 6, H / 2 + 6)
        p.append(f'<line class="edge" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" '
                 f'y2="{y2:.1f}" marker-end="url(#arr-{esc(uid)})"/>')
        if e.get("label"):
            p.append(f'<text class="elabel" x="{(x1 + x2) / 2:.1f}" '
                     f'y="{(y1 + y2) / 2 - 5:.1f}" text-anchor="middle">{esc(e["label"])}</text>')
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
    for e in view.get("edges", []):
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
    if chart["type"] == "stacked_bars":
        bars = [(b["label"], [(s["name"], s["value"]) for s in b["segments"]])
                for b in chart["bars"]]
    else:
        bars = [(i["label"], [(i["label"], i["value"])]) for i in chart["items"]]
    totals = [sum(v for _, v in segs) for _, segs in bars]
    names = list(dict.fromkeys(n for _, segs in bars for n, _ in segs))
    full, pitch = 340.0, 58
    scale = full / max(totals)
    height = len(bars) * pitch + 4
    p = [(f'<svg class="chart" viewBox="0 0 420 {height}" role="img" '
          f'aria-label="{unit} by bar" xmlns="http://www.w3.org/2000/svg">')]
    for r, ((label, segs), total) in enumerate(zip(bars, totals)):
        y = r * pitch
        p.append(f'<text class="blabel" x="0" y="{y + 14}">{esc(label)}</text>')
        x = 0.0
        for name, v in segs:
            w = v * scale
            cls = names.index(name) % 8 if chart["type"] == "stacked_bars" else 0
            p.append(f'<rect class="seg s{cls}" x="{x:.1f}" y="{y + 20}" width="{w:.1f}" '
                     f'height="26" rx="2"><title>{esc(name)}: {_num(v)} {unit}</title></rect>')
            if w >= 34:
                p.append(f'<text class="segtext" x="{x + w / 2:.1f}" y="{y + 37}" '
                         f'text-anchor="middle">{_num(v)}</text>')
            x += w
        p.append(f'<text class="btotal" x="{x + 6:.1f}" y="{y + 38}">{_num(total)} {unit}</text>')
    p.append("</svg>")
    legend = ""
    if chart["type"] == "stacked_bars":
        chips = "".join(f'<li><span class="chip s{i % 8}"></span>{esc(n)}</li>'
                        for i, n in enumerate(names))
        legend = f'<ul class="legend">{chips}</ul>'
    return "".join(p) + legend
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_study_render.py -v && .venv/bin/ruff check study tests`
Expected: 7 passed; `All checks passed!` If `test_diagram_edges_stop_at_box_borders` fails on the exact bound, print the line's x1/x2 and fix the test's arithmetic, not the clipping, provided the line visibly starts at the first box's right border and ends 6 px short of the second's left border.

- [ ] **Step 5: Commit**

```bash
git add study/text.py study/svg.py tests/test_study_render.py
git commit -m "feat: study SVG diagram and chart renderers

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The chat brief and the interview-mode prompt

**Files:**
- Create: `study/brief.py`
- Modify: `tests/test_study_render.py` (append)

- [ ] **Step 1: Append the failing tests**

```python
from study.brief import INTERVIEW_PROMPT, render_brief


def test_brief_has_every_section_in_order():
    brief = render_brief(artifact_unit())
    heads = [ln for ln in brief.splitlines() if ln.startswith("## ")]
    assert heads == [
        "## How to use this brief",
        "## Why it exists",
        "## Need to know first",
        "## System views (C4)",
        "## Core decisions",
        "## Implementation flow",
        "## Results as meaning",
        "## Interview card",
        "## Recall questions",
        "## Sources",
        "## Interview mode (paste this to an AI chat)",
    ]


def test_brief_states_views_as_text_and_decisions_with_options():
    brief = render_brief(artifact_unit())
    assert "Harness → GPU worker: submits 3 jobs" in brief
    assert "**Chosen:** Option one" in brief
    assert "**Cost:** A cost." in brief


def test_brief_ends_with_the_prompt_and_prompt_has_the_settings():
    brief = render_brief(artifact_unit())
    assert brief.rstrip().endswith(INTERVIEW_PROMPT.rstrip())
    for setting in ("AUDIENCE", "DEPTH", "MODE", "One question at a time"):
        assert setting in INTERVIEW_PROMPT


def test_prereq_brief_skips_artifact_only_sections():
    from tests.study_examples import prereq_unit
    brief = render_brief(prereq_unit())
    assert "## Core decisions" not in brief and "## Interview card" not in brief
    assert "## Concepts" in brief and "Used by: a1" in brief
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_study_render.py -v`
Expected: ImportError on `study.brief`.

- [ ] **Step 3: Implement `study/brief.py`**

```python
"""The chat brief: a unit's facts as compact markdown, ending in the interview prompt."""

from __future__ import annotations

INTERVIEW_PROMPT = """\
You are my interview coach. The brief above is the only ground truth about my project;
do not add facts it does not contain, and say "the brief does not say" when asked.

Settings (I may change these at any time):
- AUDIENCE: hiring manager | senior peer | skeptic
  (hiring manager: impact, ownership, trade-offs, what I would do differently;
   senior peer: technical depth on the decisions; skeptic: pushes on every hand-wave)
- DEPTH: pitch (30 s answer) | standard (2 to 5 minutes of follow-ups) | deep (three
  levels of "why")
- MODE: ask (you interview me) | quiz (recall questions, one at a time) | grade (I paste
  an answer, you grade it against the brief)

Default: AUDIENCE = hiring manager, DEPTH = standard, MODE = ask.

Rules:
1. One question at a time. Wait for my answer.
2. Do not reveal the brief's answers before I have answered.
3. After each answer, say what was solid, what was missing, and which stated limit I
   should have admitted. Keep it to five lines.
4. Never let me claim more than the brief supports. If I overstate, ask me to cut it
   back, and quote the limit.
5. I am a software engineer, not a researcher: reward clear reasoning about decisions
   and trade-offs over memorised numbers. A number is only useful to me as evidence for
   an answer.
6. Start now with my current settings and the first question.
"""


def _bullets(items):
    return "\n".join(f"- {i}" for i in items)


def render_brief(c: dict) -> str:
    out = [f"# {c['title']}: chat brief", ""]
    how = ("Paste this whole file into an AI chat, then paste the prompt at the end (it is "
           "already the last section). Ask clarifying questions about anything below. "
           f"About {c['minutes']} minutes to study.")
    out += ["## How to use this brief", "", how, ""]
    if c["kind"] == "artifact":
        out += ["## Why it exists", "", f"**Question:** {c['question']}", "",
                "**Requirements that drove everything:**", ""]
        out += [f"- {r['text']}. *Why:* {r['why']}" for r in c["requirements"]] + [""]
    else:
        out += ["## Concepts", "", f"Used by: {', '.join(c['used_by'])}", ""]
    if c.get("concepts"):
        if c["kind"] == "artifact":
            out += ["## Need to know first", ""]
        for t in c["concepts"]:
            line = f"- **{t['term']}**: {t['plain']}"
            if t.get("analogy"):
                line += f" Think of it as: {t['analogy']}"
            if t.get("why"):
                line += f" Why it matters: {t['why']}"
            out.append(line)
        out.append("")
    if c.get("views"):
        out += ["## System views (C4)", ""]
        for v in c["views"]:
            out += [f"### {v['title']} ({v['level']})", "", v["caption"], ""]
            labels = {n["id"]: n["label"] for n in v["nodes"]}
            for n in v["nodes"]:
                out.append(f"- **{n['label']}**" + (f": {n['sub']}" if n.get("sub") else ""))
            for e in v.get("edges", []):
                lab = f": {e['label']}" if e.get("label") else ""
                out.append(f"- {labels[e['from']]} → {labels[e['to']]}{lab}")
            out.append("")
    if c.get("decisions"):
        out += ["## Core decisions", ""]
        for d in c["decisions"]:
            out += [f"### {d['title']}", "", f"**Problem:** {d['problem']}", "",
                    "**Options considered:**", "", _bullets(d["options"]), "",
                    f"**Chosen:** {d['chosen']}", "", f"**Why:** {d['why']}", "",
                    f"**Cost:** {d['cost']}", ""]
    if c.get("flow"):
        out += ["## Implementation flow", ""]
        out += [f"{i}. **{s['label']}**: {s['detail']}" for i, s in enumerate(c["flow"], 1)]
        out.append("")
    if c.get("results"):
        out += ["## Results as meaning", ""]
        for r in c["results"]:
            out += [f"### {r['title']}", "", f"- Axis: {r['axis']}", f"- Read it as: {r['read_as']}"]
            ch = r["chart"]
            if ch["type"] == "stacked_bars":
                for b in ch["bars"]:
                    parts = ", ".join(f"{s['name']} {s['value']}" for s in b["segments"])
                    out.append(f"- {b['label']}: {parts} ({ch['unit']})")
            else:
                for i in ch["items"]:
                    out.append(f"- {i['label']}: {i['value']} {ch['unit']}")
            if r.get("so"):
                out.append(f"- So: see decision `{r['so']}`")
            out.append("")
    if c.get("interview"):
        iv = c["interview"]
        out += ["## Interview card", "", f"**30-second pitch:** {iv['pitch30']}", "",
                f"**2-minute version:** {iv['pitch120']}", "", "**Hard follow-ups:**", ""]
        for f in iv["followups"]:
            out += [f"- Q: {f['q']}", f"  A: {f['a']}"]
        out += ["", f"**Limits (what I must not claim):** {iv['limits']}", ""]
    out += ["## Recall questions", ""]
    for r in c["recall"]:
        out += [f"- Q: {r['q']}", f"  A: {r['a']}"]
    out += ["", "## Sources", ""]
    out += [f"- `{s['file']}`: {s['section']}" for s in c["sources"]]
    out += ["", "## Interview mode (paste this to an AI chat)", "", INTERVIEW_PROMPT]
    return "\n".join(out)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_study_render.py -v && .venv/bin/ruff check study tests`
Expected: 11 passed; `All checks passed!` (The prereq brief has the section order Concepts, Views, Recall, Sources, Interview mode; that is intended.)

- [ ] **Step 5: Commit**

```bash
git add study/brief.py tests/test_study_render.py
git commit -m "feat: study chat brief and interview-mode prompt

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The page renderer, checked visually

**Files:**
- Create: `study/page.py`
- Modify: `tests/test_study_render.py` (append)
- Scratch: `build/study-fixture/page.html`

**Skills to load first:** `artifact-design` and `dataviz` (palette and light/dark rules; adjust the `--c0..--c7` colours below to the dataviz skill's validated categorical palette if it differs), then `superpowers:verifying-visual-output`.

- [ ] **Step 1: Append the failing tests**

```python
from study.page import render_page


def test_page_is_self_contained_and_themed():
    page = render_page(artifact_unit())
    assert page.startswith("<!doctype html>")
    assert "<title>Example Artifact</title>" in page
    assert "<script src" not in page and "<link " not in page
    assert "prefers-color-scheme: dark" in page and 'data-theme="dark"' in page
    assert 'name="viewport"' in page


def test_page_sections_in_the_specified_order():
    page = render_page(artifact_unit())
    ids = re.findall(r'<section id="([\w-]+)"', page)
    assert ids == ["why", "concepts", "views", "decisions", "flow", "results", "interview",
                   "recall", "sources"]


def test_page_has_a_card_per_decision_and_results_link_back():
    page = render_page(artifact_unit())
    for i in range(4):
        assert f'id="d-d{i}"' in page
    assert 'href="#d-d0"' in page


def test_recall_answers_are_hidden_until_revealed():
    page = render_page(artifact_unit())
    assert "<details" in page and "<summary>Why?</summary>" in page


def test_all_four_views_render_as_tabs():
    page = render_page(artifact_unit())
    assert page.count('role="tab"') == 4 and page.count('role="tabpanel"') == 4


def test_content_is_escaped():
    u = artifact_unit()
    u["question"] = "<script>alert(1)</script>"
    assert "<script>alert(1)" not in render_page(u)


def test_prereq_page_skips_artifact_sections():
    from tests.study_examples import prereq_unit
    ids = re.findall(r'<section id="([\w-]+)"', render_page(prereq_unit()))
    assert ids == ["concepts", "views", "recall", "sources"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_study_render.py -v`
Expected: ImportError on `study.page`.

- [ ] **Step 3: Implement `study/page.py`**

```python
"""The study page: one self-contained HTML file per unit.

Sections appear in the spec's order; any section whose data is absent is skipped.
Everything is inline (CSS, SVG, a few lines of JS). The JS only switches tabs, and the
page reads fully without it.
"""

from __future__ import annotations

from study.svg import chart_html, diagram_html
from study.text import esc, inline

CSS = """
:root{--bg:#fafaf7;--fg:#1d2330;--muted:#5b6475;--card:#fff;--line:#d9dce3;
--accent:#2f5fd0;--soft:#e8eefc;--warn:#b4540a;--warnsoft:#fdf0e3;--ok:#1f7a4d;
--c0:#3b6fd4;--c1:#e07b39;--c2:#2a9d8f;--c3:#8e5bd0;--c4:#c2415a;--c5:#b59a1c;
--c6:#5a6b7d;--c7:#7a9a3a}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#14171f;
--fg:#e6e8ee;--muted:#9aa3b5;--card:#1c202b;--line:#323849;--accent:#7ea2ff;
--soft:#222b45;--warn:#f0a15e;--warnsoft:#33261a;--ok:#5fcf9a;--c0:#6c97f0;--c1:#f0a15e;
--c2:#4fc2b3;--c3:#b48cf0;--c4:#ef7a92;--c5:#d8c04a;--c6:#93a3b5;--c7:#a6c75f}}
:root[data-theme="dark"]{--bg:#14171f;--fg:#e6e8ee;--muted:#9aa3b5;--card:#1c202b;
--line:#323849;--accent:#7ea2ff;--soft:#222b45;--warn:#f0a15e;--warnsoft:#33261a;
--ok:#5fcf9a;--c0:#6c97f0;--c1:#f0a15e;--c2:#4fc2b3;--c3:#b48cf0;--c4:#ef7a92;
--c5:#d8c04a;--c6:#93a3b5;--c7:#a6c75f}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:0 16px 64px}
header.hero{padding:32px 0 8px}
.kicker{color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.06em}
h1{font-size:28px;line-height:1.2;margin:6px 0 10px}
h2{font-size:21px;margin:0 0 12px}
h3{font-size:16px;margin:0 0 6px}
.lead{font-size:18px}
nav.pills{position:sticky;top:0;background:var(--bg);padding:8px 0;display:flex;gap:6px;
flex-wrap:wrap;z-index:2;border-bottom:1px solid var(--line)}
nav.pills a{padding:3px 10px;border:1px solid var(--line);border-radius:99px;
color:var(--fg);text-decoration:none;font-size:13px}
section{margin-top:36px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;margin:10px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}
.why{color:var(--muted);font-size:14px}
.row{margin:6px 0}.row b{display:inline-block;min-width:76px;color:var(--muted);
font-weight:600;font-size:13px;text-transform:uppercase;letter-spacing:.04em}
.opt{display:inline-block;margin:2px 6px 2px 0;padding:2px 10px;border:1px solid var(--line);
border-radius:99px;font-size:14px}.opt.chosen{background:var(--soft);border-color:var(--accent);
font-weight:600}
.cost{color:var(--warn)}
.tabs{display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap}
.tabs button{font:inherit;font-size:14px;padding:5px 12px;border:1px solid var(--line);
background:var(--card);color:var(--fg);border-radius:8px;cursor:pointer}
.tabs button[aria-selected="true"]{background:var(--soft);border-color:var(--accent);
font-weight:600}
.diagram{width:100%;height:auto;display:block}
.diagram-text{display:none;font-size:15px}
.edge{stroke:var(--muted);stroke-width:1.5}.arrow{fill:var(--muted)}
.elabel{font-size:11px;fill:var(--muted);paint-order:stroke;stroke:var(--bg);stroke-width:4px}
.node rect{fill:var(--card);stroke:var(--accent);stroke-width:1.5}
.node.k-person rect{fill:var(--soft)}.node.k-external rect{stroke:var(--muted);
stroke-dasharray:4 3}.node.k-store rect{fill:var(--warnsoft);stroke:var(--warn)}
.node.k-focus rect{fill:var(--soft);stroke-width:2.5}
.nlabel{font-size:13px;font-weight:600;fill:var(--fg)}.nsub{font-size:11px;fill:var(--muted)}
.chart{width:100%;max-width:520px;height:auto;display:block}
.blabel{font-size:12px;fill:var(--fg);font-weight:600}.segtext{font-size:11px;fill:#fff}
.btotal{font-size:12px;fill:var(--fg)}
.seg.s0,.chip.s0{fill:var(--c0);background:var(--c0)}.seg.s1,.chip.s1{fill:var(--c1);background:var(--c1)}
.seg.s2,.chip.s2{fill:var(--c2);background:var(--c2)}.seg.s3,.chip.s3{fill:var(--c3);background:var(--c3)}
.seg.s4,.chip.s4{fill:var(--c4);background:var(--c4)}.seg.s5,.chip.s5{fill:var(--c5);background:var(--c5)}
.seg.s6,.chip.s6{fill:var(--c6);background:var(--c6)}.seg.s7,.chip.s7{fill:var(--c7);background:var(--c7)}
.legend{list-style:none;padding:0;margin:6px 0;display:flex;gap:14px;flex-wrap:wrap;font-size:13px}
.chip{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
.flow{display:flex;gap:8px;flex-wrap:wrap;counter-reset:s}
.step{flex:1 1 160px;background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:10px 12px;position:relative}.step:before{counter-increment:s;content:counter(s);
position:absolute;top:-10px;left:10px;background:var(--accent);color:var(--bg);width:20px;
height:20px;border-radius:50%;font-size:12px;text-align:center;line-height:20px}
.callout{border-left:4px solid var(--accent);padding:6px 12px;background:var(--soft);
border-radius:0 8px 8px 0;margin:8px 0}
.limits{border-left-color:var(--warn);background:var(--warnsoft)}
details{background:var(--card);border:1px solid var(--line);border-radius:8px;
padding:8px 12px;margin:6px 0}summary{cursor:pointer;font-weight:600}
code{font-size:.92em;background:var(--soft);padding:1px 5px;border-radius:4px}
footer.src{font-size:13px;color:var(--muted)}
@media (max-width:600px){.diagram{display:none}.diagram-text{display:block}
h1{font-size:24px}.lead{font-size:16px}}
"""

JS = """
for (const g of document.querySelectorAll('[data-tabs]')) {
  const tabs = g.querySelectorAll('[role=tab]'), panels = g.querySelectorAll('[role=tabpanel]');
  const show = i => { tabs.forEach((t, j) => t.setAttribute('aria-selected', j === i));
    panels.forEach((p, j) => { p.hidden = j !== i; }); };
  tabs.forEach((t, i) => t.addEventListener('click', () => show(i)));
  show(0);
}
"""

LEVEL_NAMES = {"context": "1 Context", "container": "2 Containers",
               "component": "3 Components", "dynamic": "4 One run"}


def _concepts(c):
    cards = []
    for t in c["concepts"]:
        extra = ""
        if t.get("analogy"):
            extra += f'<div class="row"><b>Like</b>{inline(t["analogy"])}</div>'
        if t.get("why"):
            extra += f'<div class="row"><b>Matters</b>{inline(t["why"])}</div>'
        cards.append(f'<div class="card"><h3>{esc(t["term"])}</h3>'
                     f'<div>{inline(t["plain"])}</div>{extra}</div>')
    title = "Need to know first" if c["kind"] == "artifact" else "The ideas"
    return f'<section id="concepts"><h2>{title}</h2><div class="grid">{"".join(cards)}</div></section>'


def _views(c):
    tabs, panels = [], []
    for i, v in enumerate(c["views"]):
        name = LEVEL_NAMES.get(v["level"], v["title"])
        tabs.append(f'<button role="tab" aria-selected="false">{esc(name)}</button>')
        panels.append(f'<div role="tabpanel"><h3>{esc(v["title"])}</h3>'
                      f'<p class="why">{inline(v["caption"])}</p>'
                      f'{diagram_html(v, f"{c["id"]}-{i}")}</div>')
    head = "System views" + (" (C4)" if c["kind"] == "artifact" else "")
    return (f'<section id="views"><h2>{head}</h2><div class="card" data-tabs>'
            f'<div class="tabs" role="tablist">{"".join(tabs)}</div>{"".join(panels)}</div>'
            "</section>")


def _decisions(c):
    cards = []
    for d in c["decisions"]:
        opts = "".join(
            f'<span class="opt{" chosen" if o == d["chosen"] else ""}">{inline(o)}</span>'
            for o in d["options"])
        cards.append(
            f'<div class="card" id="d-{esc(d["id"])}"><h3>{esc(d["title"])}</h3>'
            f'<div class="row"><b>Problem</b>{inline(d["problem"])}</div>'
            f'<div class="row"><b>Options</b>{opts}</div>'
            f'<div class="row"><b>Chose</b>{inline(d["chosen"])}</div>'
            f'<div class="row"><b>Because</b>{inline(d["why"])}</div>'
            f'<div class="row cost"><b>Cost</b>{inline(d["cost"])}</div></div>')
    return f'<section id="decisions"><h2>Core decisions</h2>{"".join(cards)}</section>'


def _results(c):
    titles = {d["id"]: d["title"] for d in c.get("decisions", [])}
    cards = []
    for i, r in enumerate(c["results"]):
        so = ""
        if r.get("so"):
            so = (f'<div class="callout">So: <a href="#d-{esc(r["so"])}">'
                  f'{esc(titles[r["so"]])}</a></div>')
        cards.append(
            f'<div class="card"><h3>{esc(r["title"])}</h3>{chart_html(r["chart"], f"r{i}")}'
            f'<div class="row"><b>Axis</b>{inline(r["axis"])}</div>'
            f'<div class="row"><b>Read it as</b>{inline(r["read_as"])}</div>{so}</div>')
    return f'<section id="results"><h2>Results, as meaning</h2>{"".join(cards)}</section>'


def _interview(c):
    iv = c["interview"]
    fu = "".join(f"<details><summary>{inline(f['q'])}</summary><p>{inline(f['a'])}</p></details>"
                 for f in iv["followups"])
    return (
        '<section id="interview"><h2>Interview card</h2>'
        f'<div class="callout"><b>30 seconds.</b> {inline(iv["pitch30"])}</div>'
        f'<details><summary>The 2-minute version</summary><p>{inline(iv["pitch120"])}</p></details>'
        f'<h3>Hard follow-ups</h3>{fu}'
        f'<div class="callout limits"><b>Limits: do not claim more.</b> '
        f'{inline(iv["limits"])}</div>'
        '<p class="why">To practise out loud, paste this unit\'s <code>brief.md</code> into an '
        'AI chat; its last section is the interview-mode prompt.</p></section>')


def render_page(c: dict) -> str:
    art = c["kind"] == "artifact"
    sections, nav = [], []

    def add(sid, label, html):
        sections.append(html)
        nav.append(f'<a href="#{sid}">{label}</a>')

    if art:
        reqs = "".join(f'<div class="card"><b>{inline(r["text"])}</b>'
                       f'<div class="why">{inline(r["why"])}</div></div>'
                       for r in c["requirements"])
        add("why", "Why", f'<section id="why"><h2>Why it exists</h2>'
            f'<p class="lead">{inline(c["question"])}</p>'
            f'<h3>Requirements that drove everything</h3><div class="grid">{reqs}</div></section>')
    if c.get("concepts"):
        add("concepts", "Concepts", _concepts(c))
    if c.get("views"):
        add("views", "Views", _views(c))
    if c.get("decisions"):
        add("decisions", "Decisions", _decisions(c))
    if c.get("flow"):
        steps = "".join(f'<div class="step"><b>{inline(s["label"])}</b>'
                        f'<div class="why">{inline(s["detail"])}</div></div>' for s in c["flow"])
        add("flow", "Flow", f'<section id="flow"><h2>Implementation flow</h2>'
            f'<div class="flow">{steps}</div></section>')
    if c.get("results"):
        add("results", "Results", _results(c))
    if c.get("interview"):
        add("interview", "Interview", _interview(c))
    rec = "".join(f"<details><summary>{inline(r['q'])}</summary><p>{inline(r['a'])}</p></details>"
                  for r in c["recall"])
    add("recall", "Recall", f'<section id="recall"><h2>Recall check</h2>'
        f'<p class="why">Answer out loud first, then open.</p>{rec}</section>')
    src = "".join(f"<li><code>{esc(s['file'])}</code>: {esc(s['section'])}</li>"
                  for s in c["sources"])
    add("sources", "Sources", f'<section id="sources"><footer class="src"><h2>Sources</h2>'
        f'<ul>{src}</ul></footer></section>')

    used = "" if art else f'<p class="why">Used by: {esc(", ".join(c["used_by"]))}</p>'
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{esc(c["short_title"])}</title><style>{CSS}</style></head><body><main>'
        f'<header class="hero"><div class="kicker">Study page · about {c["minutes"]} min</div>'
        f'<h1>{esc(c["title"])}</h1>{used}</header>'
        f'<nav class="pills">{"".join(nav)}</nav>{"".join(sections)}</main>'
        f'<script>{JS}</script></body></html>')
```

(The hero deliberately shows no question line: the question opens the "Why it exists" section.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_study_render.py -v && .venv/bin/ruff check study tests`
Expected: 18 passed; `All checks passed!` (ruff may flag line length in `CSS`; wrap the offending lines rather than disabling the rule.)

- [ ] **Step 5: Visual check on a fixture page (mandatory; DOM presence is not evidence)**

```bash
mkdir -p build/study-fixture
.venv/bin/python - <<'EOF'
from pathlib import Path
from study.page import render_page
from tests.study_examples import artifact_unit
Path("build/study-fixture/page.html").write_text(render_page(artifact_unit()))
EOF
```

Open `http://127.0.0.1:8765/build/study-fixture/page.html` (preview config `post-preview`, repo root). Take screenshots at 1280 px and 375 px, light and dark (`resize_window` `colorScheme`). Check by looking, and record what you saw: (a) the C4 tab bar switches panels on click, (b) boxes are not overlapped by edge labels, (c) the stacked bar's tiny "compile 0.3" segment is a sliver without a label and the totals are not clipped, (d) on 375 px there is no horizontal page scroll (`document.documentElement.scrollWidth <= 375` via javascript_tool) and the diagram is replaced by the text list, (e) dark mode text is readable, (f) summary elements open. Fix CSS or `svg.py` until all six hold; do not commit with a failing check.

- [ ] **Step 6: Commit**

```bash
git add study/page.py tests/test_study_render.py
git commit -m "feat: study page renderer, checked at desktop and phone, light and dark

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Build function, CLI and the traceability checks

**Files:**
- Create: `study/trace.py`, `study/build.py`, `scripts/build_study.py`, `tests/test_study_units.py`
- Modify: `tests/test_study_render.py` (append trace tests)

- [ ] **Step 1: Append the failing tests for tracing**

```python
from pathlib import Path

from study.trace import missing_sections, untraced_numbers


def _write(tmp_path, name, text):
    p = Path(tmp_path) / name
    p.write_text(text)
    return str(p)


def test_numbers_in_sources_are_traced_and_others_flagged(tmp_path):
    src = _write(tmp_path, "post.md", "# Title\nMedian 81.12 s and 35,792 tokens.\n")
    u = artifact_unit()
    u["results"] = []
    u["sources"] = [{"file": src, "section": "Title"}]
    u["question"] = "Is 81.12 real, and 35792, and 12.34?"
    flagged = untraced_numbers(u)
    assert flagged == ["12.34"]


def test_small_integers_and_years_are_ignored(tmp_path):
    src = _write(tmp_path, "post.md", "# Title\nnothing numeric\n")
    u = artifact_unit()
    u["results"] = []
    u["sources"] = [{"file": src, "section": "Title"}]
    u["question"] = "Three arms, 4 phases, 300 runs in 2026?"
    assert untraced_numbers(u) == ["300"]


def test_derived_numbers_must_be_declared_with_a_how(tmp_path):
    src = _write(tmp_path, "post.md", "# Title\n")
    u = artifact_unit()
    u["results"] = []
    u["sources"] = [{"file": src, "section": "Title"}]
    u["question"] = "About 10.39 s."
    u["derived_numbers"] = [{"value": "10.39", "how": "difference of two medians"}]
    assert untraced_numbers(u) == []


def test_missing_section_is_reported(tmp_path):
    src = _write(tmp_path, "post.md", "# Title\n")
    u = artifact_unit()
    u["sources"] = [{"file": src, "section": "Title"}, {"file": src, "section": "Nowhere"}]
    assert missing_sections(u) == [f"{src}: Nowhere"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_study_render.py -v`
Expected: ImportError on `study.trace`.

- [ ] **Step 3: Implement**

`study/trace.py`:

```python
"""Traceability: every number in a unit's text must appear in a source it cites.

A number counts if it has a decimal point or three or more digits (small integers such
as "three arms" are prose), and is not a year. It is traced if the same digits appear in
one of the unit's source files, or if the unit declares it in `derived_numbers` with a
reason. Section citations must be exact substrings of their file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _normalise(token: str) -> str:
    return token.replace(",", "")


def _significant(token: str) -> bool:
    t = _normalise(token)
    if re.fullmatch(r"(19|20)\d\d", t):
        return False
    return "." in t or len(t) >= 3


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            if k not in ("sources", "derived_numbers"):
                yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def _numbers_in(node):
    out = []
    for s in _strings(node):
        out += [_normalise(t) for t in NUMBER.findall(s) if _significant(t)]
    # chart values are numbers, not strings
    for r in node.get("results", []) if isinstance(node, dict) else []:
        ch = r["chart"]
        vals = ([s["value"] for b in ch["bars"] for s in b["segments"]]
                if ch["type"] == "stacked_bars" else [i["value"] for i in ch["items"]])
        out += [_normalise(f"{v:g}") for v in vals if _significant(f"{v:g}")]
    return out


def _read(path: str) -> str:
    return Path(path).expanduser().read_text()


def untraced_numbers(content: dict) -> list[str]:
    known = set()
    for s in content["sources"]:
        known |= {_normalise(t) for t in NUMBER.findall(_read(s["file"]))}
    known |= {_normalise(str(d["value"])) for d in content.get("derived_numbers", [])}
    seen, flagged = set(), []
    for n in _numbers_in(content):
        if n not in known and n not in seen:
            flagged.append(n)
        seen.add(n)
    return flagged


def missing_sections(content: dict) -> list[str]:
    return [f"{s['file']}: {s['section']}" for s in content["sources"]
            if s["section"] not in _read(s["file"])]


def load(unit_dir: Path) -> dict:
    return json.loads((unit_dir / "content.json").read_text())
```

Two details the implementer must keep: the stacked-chart float check formats values with `:g` so `40.5` becomes `40.5` and `35792` stays `35792` (a `bars` value of `43040.0` would otherwise read `43040.0`); and a `derived_numbers` entry without a non-empty `how` must be rejected: add to `study/schema.py` `validate` the loop `for d in c.get("derived_numbers", []): _get(d, "value", str, where); _get(d, "how", str, where)` and a test `test_derived_number_needs_a_how` in `tests/test_study_schema.py` (set `u["derived_numbers"] = [{"value": "1.5"}]`, expect `ContentError` matching `how`). Run both test files.

`study/build.py`:

```python
"""Build a unit's page and brief from its content.json."""

from __future__ import annotations

from pathlib import Path

from study.brief import render_brief
from study.page import render_page
from study.schema import validate
from study.trace import load

STUDY_DIR = Path(__file__).resolve().parents[1] / "docs" / "learning" / "study"


def build_unit(unit_dir: Path) -> tuple[str, str]:
    content = load(unit_dir)
    validate(content)
    return render_page(content), render_brief(content)
```

`scripts/build_study.py`:

```python
"""Write page.html and brief.md for every study unit (or the named ones).

    .venv/bin/python scripts/build_study.py [unit ...]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from study.build import STUDY_DIR, build_unit


def main(argv: list[str]) -> int:
    names = argv or sorted(p.parent.name for p in STUDY_DIR.glob("*/content.json"))
    for name in names:
        page, brief = build_unit(STUDY_DIR / name)
        (STUDY_DIR / name / "page.html").write_text(page)
        (STUDY_DIR / name / "brief.md").write_text(brief)
        print(f"built {name}: {len(page):,} B page, {len(brief):,} B brief")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

`tests/test_study_units.py` (data-driven; passes vacuously until units exist, then guards each one):

```python
import pytest

from study.build import STUDY_DIR, build_unit
from study.trace import load, missing_sections, untraced_numbers

UNITS = sorted(p.parent for p in STUDY_DIR.glob("*/content.json"))
IDS = [u.name for u in UNITS]


@pytest.mark.parametrize("unit", UNITS, ids=IDS)
def test_outputs_are_in_sync_with_content(unit):
    page, brief = build_unit(unit)
    assert (unit / "page.html").read_text() == page, "run scripts/build_study.py"
    assert (unit / "brief.md").read_text() == brief, "run scripts/build_study.py"


@pytest.mark.parametrize("unit", UNITS, ids=IDS)
def test_every_number_traces_to_a_cited_source(unit):
    assert untraced_numbers(load(unit)) == []


@pytest.mark.parametrize("unit", UNITS, ids=IDS)
def test_every_cited_section_exists(unit):
    assert missing_sections(load(unit)) == []
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_study_schema.py tests/test_study_render.py tests/test_study_units.py -v && .venv/bin/ruff check study scripts/build_study.py tests`
Expected: all pass (schema 14, render 22, units 0 collected as parametrised-empty is reported as skipped or deselected; confirm pytest exits 0). `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add study/trace.py study/build.py scripts/build_study.py tests/test_study_units.py tests/test_study_render.py tests/test_study_schema.py study/schema.py
git commit -m "feat: study build, CLI and source-traceability checks

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Unit P1, "LLM serving on a GPU"

**Files:**
- Create: `docs/learning/study/p1/content.json` (then generated `page.html`, `brief.md`)

**Read first (all of it, not skimmed):** `docs/post.md` ("What was measured", "The decomposition", "KV capacity — the second dividend", "The four mechanisms"); `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md` §9b modules 1 to 3 (lines ~972 to 1060); `docs/post-a2.md` "The service curve"; `explainer/terms.json`. One correction already known and owed to the owner: **Q is not cached; only K and V are** (`docs/learning/progress.md`, module 0). Use it.

**Content brief.** `kind: "prereq"`, `id: "p1"`, `title: "LLM serving on a GPU"`, `short_title: "LLM Serving Basics"`, `minutes: 20`, `used_by: ["a1", "a2", "a4", "a5"]`. The owner wants intuition in simple terms, not detail. Write for someone who has used an LLM API but never run one.

- `concepts` (6 to 8, each with `term`, `plain` of one or two sentences, `analogy`, `why` stating what it explains in the artifacts): GPU memory (HBM) and the three things that fill it (weights, scratch space for one forward pass, the KV cache); weights; the KV cache (K and V, not Q) and why cache size is the concurrency limit; what vLLM is (an engine that loads a model, sizes the cache, and serves many requests at once); continuous batching; cold start; serverless GPUs (scale to zero, why the first request is slow); `torch.compile` and CUDA graphs in one card.
- `views` (2, `level: "concept"`): (1) "Where GPU memory goes": nodes for GPU memory, weights, scratch space, KV cache with edges "holds"; (2) "What a vLLM replica does before it can answer": a left-to-right chain, start process, load weights, compile, memory profiling, capture graphs, health check ready, first request. Use only steps named in `docs/post.md` "The decomposition" and "The four mechanisms".
- `results`: one `stacked_bars` chart of arm A's phases from `docs/post.md` "The decomposition" (median seconds: platform 4.37, weights 45.83, compile 19.01, profiling 0.09, graph capture 4.00, unattributed 4.46, ready 4.43, cold first token 0.30) titled "Where a cold start's 81 seconds go", `axis` "Seconds, median over runs, one bar per cache set-up", `read_as` saying that the longest segment is where waiting happens and that this unit uses it only to show the shape, no decision link (omit `so`).
- `recall`: 5 to 6 questions on why, not numbers, e.g. why the cache size divides into a number of concurrent requests; why the engine must run the model once before serving; why a serverless GPU's first request is slow.
- `sources`: each file and an exact heading or phrase from it, verified by `missing_sections`.

- [ ] **Step 1: Read the sources and draft the facts**

Read the files above. For each concept write down, in your working notes, the sentence in the source that supports it. A concept with no supporting sentence is cut, not filled from memory.

- [ ] **Step 2: Write `content.json`**

Write the file to the schema in `study/schema.py` and the shape of `tests/study_examples.py::prereq_unit`. Quote numbers exactly as they appear in the sources.

- [ ] **Step 3: Build and run the checks**

```bash
.venv/bin/python scripts/build_study.py p1
.venv/bin/python -m pytest tests/test_study_units.py -v
```
Expected: `built p1: ...`, then the three tests for `p1` pass. If `untraced_numbers` lists a number, find it in the source and fix the unit, or declare it in `derived_numbers` with the arithmetic in `how` if it is a derivation.

- [ ] **Step 4: Commit**

```bash
git add docs/learning/study/p1
git commit -m "docs: study unit P1, LLM serving on a GPU

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Unit A1, "Where a vLLM cold start goes"

**Files:**
- Create: `docs/learning/study/a1/content.json` (then generated `page.html`, `brief.md`)

**Read first (all of it):** `docs/post.md` (whole); `docs/experiment.md` (whole: arms, hypotheses H1 to H5, analysis plan, exclusion rules, stopping rule, headline rule); `harness/README.md`; `coldstart/driver.py`, `coldstart/cache_config.py`, `coldstart/schema.py`, `worker/handler.py`, `harness/campaign.py`, `harness/scheduler.py`, `harness/recorder.py`, `harness/stats.py` (docstrings and public functions are enough; read the bodies where a claim depends on them); the cold-start design spec §1 "Context and goal" and §9b. The four-views diagrams below must be drawn from what the code and `harness/README.md` say the components are, not from the seeds.

**Seeds, to be confirmed or replaced by reading.** If a seed is not supported, replace it and list the replacement in the closing note.

- `question`: which part of a vLLM cold start dominates, and what does a warm weight cache versus a warm compile cache each buy?
- `requirements` (4 to 5, each `text` + `why`): break one cold start into phases that sum to the total with nothing hidden in a residual; compare cache set-ups that differ in exactly one thing; report the distribution and its uncertainty, not a mean; fix hypotheses, exclusion rules and the headline-selection rule before looking at data; make every published number re-derivable from committed data on a laptop.
- `concepts`: 2 to 3 cards only for things not in P1: arms A, B, C and what each caches; "contrast" and "difference of contrasts" in plain words; "pre-registration" in one sentence. Everything else links to P1 by name in the card text.
- `views`: `context` (author and reader around the study, RunPod serverless, the model hub, the network volume), `container` (driver and scheduler on the laptop, the RunPod endpoint and worker image running vLLM, the network volume, the append-only JSONL store, the analysis and figures), `component` (inside the worker or inside the harness, whichever the code shows is the part that explains "phases that sum to the total": the recorder's monotonic stage marks, the vLLM log parser, the record), `dynamic` (one run, in order: schedule picks the arm, driver submits, worker cold-starts through the stages, record returned, appended to the store). Each node label at most 22 characters, sub at most 60. At most four columns by four rows.
- `decisions` (4 to 6; candidates): (1) three arms that differ in exactly one interface; (2) randomised interleaved triples, so platform drift is not confounded with arm, and every triple is paired within a host; (3) prime the compile cache outside the measured runs, because otherwise arm C is a mixture whose effect grows with run index; (4) the headline is chosen by a pre-registered rule and states the difference of the two contrasts with its interval; (5) report no p99 at 100 runs per arm, and report the host-heterogeneity question (H4) as unanswerable instead of dropping it; (6) the artifact-agnostic part of the harness was extracted into `harness/` for artifacts 2 to 5 (only keep this if `harness/README.md` and the extraction plan support it as a decision of this artifact). For each: `problem`, two or more `options` (include the rejected one; read the spec for what was actually considered), `chosen`, `why`, `cost`.
- `flow`: 5 to 7 steps from design to claim, from the spec and `harness/README.md`: pre-register, prime the cache, run the interleaved schedule, store append-only, partition publishable rows, analyse with bootstrap, publish figures and the post.
- `results`: (a) `stacked_bars` of the three arms' medians per phase from `docs/post.md` "The decomposition", `so` pointing at the arms decision; `axis` says "seconds, median per phase"; `read_as` says the compile segment almost vanishes in arm C while weights shrink from A to C; (b) `bars` of KV cache tokens by arm (A 35,792; B 35,792; C 43,040) with `read_as` saying this is memory the compile cache gives back, the permanent consequence of profiling under a cold compile; `so` the profiling/priming decision it belongs to, or omit `so` if no decision fits.
- `interview`: `pitch30`, `pitch120` in first person, spoken-English, no numbers except at most two; `followups` (4 to 6) including: why three arms, why pre-register, what surprised you, what would you do differently, what does it not tell you; `limits` from `docs/post.md` "Scope" and the H4 failure (one provider, one GPU model, one model, one engine version, one region, one host).
- `recall` (6 to 8): questions on the requirements and decisions, not on numbers.
- `sources`: every file read above, each with an exact heading or phrase.

- [ ] **Step 1: Read the sources**

Read everything listed. Record, in the closing note, any seed the sources contradict.

- [ ] **Step 2: Write `content.json`**

Follow the schema; copy numbers only as they appear in the sources.

- [ ] **Step 3: Build and run the checks**

```bash
.venv/bin/python scripts/build_study.py a1
.venv/bin/python -m pytest tests/test_study_units.py -v
```
Expected: the three tests for `a1` pass (sync, traceability, sections). Fix the content, not the tests.

- [ ] **Step 4: Commit**

```bash
git add docs/learning/study/a1
git commit -m "docs: study unit A1, where a vLLM cold start goes

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Independent accuracy review of both units

The owner has twice caught unverified claims, and the number test cannot catch a wrong sentence. A reviewer who has not seen the drafting reads the sources fresh.

**Files:**
- Read: `docs/learning/study/p1/content.json`, `docs/learning/study/a1/content.json` and their cited sources
- Modify (only if findings): the two `content.json` files, then rebuild

- [ ] **Step 1: Dispatch the reviewer**

Use the Agent tool, `subagent_type: "general-purpose"`, prompt: "Review `docs/learning/study/p1/content.json` and `docs/learning/study/a1/content.json` for factual accuracy only. For every sentence that states a fact about the experiment, the system, a decision, a result or a limit, find the supporting text in the files listed in that unit's `sources` (and, for architecture claims, the code under `coldstart/`, `harness/`, `worker/`) and classify it supported / overstated / unsupported / contradicted, quoting the source. Check especially: (1) every statement of what a decision's rejected option was, (2) every 'why' (is it the source's reason or an invention), (3) the C4 views against the code, (4) the limits against `docs/post.md` 'Scope' and the H4 section, (5) that no simplification claims more than the post does. Report only the not-supported ones, with file, field, the sentence, and the source line. Do not edit files."

- [ ] **Step 2: Fix each finding or record why not**

For each reported item either correct the `content.json` field (quote the source) or, if the reviewer is wrong, write one line saying why. Do not weaken the reviewer's request by editing only until it passes: if a decision's "options considered" cannot be supported, replace it with only what the spec states, or cut the decision to bring the list to 4.

- [ ] **Step 3: Rebuild and re-run**

```bash
.venv/bin/python scripts/build_study.py p1 a1
.venv/bin/python -m pytest tests/test_study_schema.py tests/test_study_render.py tests/test_study_units.py -v
.venv/bin/ruff check study scripts/build_study.py tests
```
Expected: all pass; `All checks passed!`

- [ ] **Step 4: Commit if anything changed**

```bash
git add docs/learning/study/p1 docs/learning/study/a1
git commit -m "docs: correct study units P1 and A1 after the accuracy review

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Visual verification, index, and the owner's format review (manual checkpoint)

**Files:**
- Create: `docs/learning/study/README.md`

Load `superpowers:verifying-visual-output` first.

- [ ] **Step 1: Screenshot both real pages at both widths and both themes**

For `p1` and `a1`, open `http://127.0.0.1:8765/docs/learning/study/<unit>/page.html`; at 1280 px and 375 px (and dark mode at each), take screenshots of the full page (scroll and capture, or `browser_take_screenshot` with full-page). Save under `build/study-checks/`. Look at them and write down: does every diagram have readable labels with no overlap? does the phone show the text alternative and no horizontal scroll (`document.documentElement.scrollWidth <= window.innerWidth`)? are chart segments proportional and the 0.3 s sliver not mislabelled? is dark mode readable? Fix defects in `study/*.py` and re-run the tests; rebuild.

- [ ] **Step 2: Exercise the interactions**

With the browser tool, click each C4 tab on A1 and confirm the panel changes (read the visible heading after each click); open one recall item and one follow-up and confirm the answer appears; click a result's "So:" link and confirm it scrolls to the decision card (check `location.hash`). Report what you saw.

- [ ] **Step 3: Check the brief in a real paste**

Print `docs/learning/study/a1/brief.md`; confirm it reads as a standalone document: no references to "the page", a glossary-level `Need to know first`, and the interview prompt last. Read the prompt once as the AI chat would: could it run without any other context? State one sentence for the answer.

- [ ] **Step 4: Write the index**

`docs/learning/study/README.md`: a table of units (id, title, minutes, files), "How to study" in four lines (read P1 once; for an artifact, read the page top to bottom, then answer the recall check out loud; then paste `brief.md` into an AI chat and run the interview mode), the interview-mode settings in one line, and a placeholder-free "Published pages" table that lists `P1` and `A1` with the URL once published (Step 6) and `P2`, `A2`, `A4`, `A5`, `A6`, `A7` marked "after the pilot is approved".

- [ ] **Step 5: Run the full suite for the touched areas and show the output**

```bash
.venv/bin/python -m pytest tests/test_study_schema.py tests/test_study_render.py tests/test_study_units.py -v
.venv/bin/ruff check study scripts/build_study.py tests
.venv/bin/python -m pytest -q 2>&1 | tail -5
git status --short
```
Expected: the study tests pass; the whole suite's count is unchanged apart from the new tests and no new failure (if the full suite has pre-existing failures, state them with their names; do not claim "all green"); `git status` shows nothing staged beyond this task's files and the three files that other sessions modified remain unstaged.

- [ ] **Step 6: Publish the two pages as private Artifacts**

Load the `artifact-design` skill, then publish `docs/learning/study/p1/page.html` and `docs/learning/study/a1/page.html` with the Artifact tool (private by default; `icon` "book"; description one sentence each). Add each returned URL to the README's table. Do not publish anything else.

- [ ] **Step 7: Commit**

```bash
git add docs/learning/study/README.md
git commit -m "docs: study index with the pilot units' published pages

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 8: Stop and hand the pilot to the owner (the format gate)**

Do not start P2 or A2, A4, A5, A6 or A7. Send the owner both URLs and `docs/learning/study/a1/brief.md`, plus the keep/drop log from Task 1 for sign-off on the intentional drops. Ask exactly these questions: (1) Is the density right, or still too text-heavy? (2) Do the four C4 views help? (3) Does each decision card give you the "why" you wanted? (4) Run the brief's interview mode in a fresh chat for one round and say what felt wrong. (5) Sign off the Task 1 drops. Record the answers; template changes happen in `study/` once, here, before any fan-out.

---

## Self-review

**Spec coverage.** Goal and scope: P1 and A1 only, A6 and A7 deferred to fan-out (Task 10 Step 8). Deliverables, `page.html` plus `brief.md` per unit: Tasks 7 and 8, built by Task 6. Shared prerequisites P1: Task 7; P2 is deliberately not in the pilot (the spec's build order puts it in the fan-out). Page template, seven sections in order: Task 5 test `test_page_sections_in_the_specified_order`. C4 views, no code level, one dynamic: schema requires the four levels (Task 2). Decisions 4 to 6 with option/choice/why/cost: schema and Task 8. Results as meaning with axis/read-as/so: schema, renderer, Task 8. Interview card with limits: Tasks 5 and 8. Interview mode settings (audience, depth, mode, rules): `INTERVIEW_PROMPT`, tested in Task 4. Sourcing rules: traceability and cited-section tests (Task 6), reviewer pass (Task 9). Verification at desktop and phone with interaction clicks: Tasks 5 and 10. Build order and the review gate: Task 10 Step 8. Spec step 4, recording URLs in `plan.md`/`progress.md`: **deviation, deliberate**: those files hold other sessions' uncommitted work, so the URLs go in `docs/learning/study/README.md`, and adding one pointer line to `plan.md` is left for the owner once those sessions are committed; the spec's risks section already anticipates this.

**Placeholder scan.** No TBD or "fill in later". Content tasks (7, 8) give seeds and a schema rather than the finished prose, because the prose must be written from sources read in the task; each states the verification (tracing, section check, reviewer) that replaces a transcribed answer. One honest known wart is called out in Task 5 (`lead if False`), with the instruction to delete it.

**Type consistency.** `diagram_html(view, uid)` and `chart_html(chart, uid)` are the names used in tests and `page.py`. `render_brief`, `render_page`, `validate`, `build_unit`, `untraced_numbers`, `missing_sections`, `load` are used with the same signatures throughout. Content keys (`short_title`, `used_by`, `derived_numbers`, `concepts`, `views[].level` with `"concept"` for prereqs) match between schema, example fixtures, brief and page.

**UI audit.** Every UI task has a non-DOM check (screenshots and computed overflow at 375 px, interaction clicks, light/dark). No encapsulation boundary. No visible UI removed. The plan ends with a manual checkpoint (Task 10) at both widths.

**Parity audit.** Task 1 inventories the existing explainer by reading its code, logs a keep/drop decision for each capability and records the baseline screenshots; nothing is deleted anywhere in this plan, so there is no deletion task, and the owner's sign-off on observable drops is requested in Task 10.
