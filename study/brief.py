"""The chat brief: a unit's facts as compact markdown, ending in the interview prompt."""

from __future__ import annotations

from study.schema import flow_phases, merged_segments, phased, so_ids
from study.seq import numbered, step_line
from study.text import plural, resolve_links

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


def _num(v):
    """A summed value without float noise: 18.79 + 8.0 prints 26.79."""
    return str(round(v, 6))


def _sentence(text):
    """The text ending in exactly one full stop (it may already end in one)."""
    return text.rstrip().rstrip(".") + "."


def _relationships(c):
    """Who serves whom, as text: requirement -> decisions, decision -> concepts,
    result -> decisions, each link with its stated reason."""
    if not any("id" in r for r in c.get("requirements", [])):
        return []
    decisions = c["decisions"]
    out = ["## Relationships", "", "**Requirements and the decisions that meet them:**", ""]
    for r in c["requirements"]:
        out.append(f"- {r['id']}: {r['text']}")
        links = [(d, s) for d in decisions for s in d.get("serves", []) if s["req"] == r["id"]]
        out += [f"  - `{d['id']}` {d['title']}: {s['because']}" for d, s in links]
        if not links and r.get("unlinked_reason"):
            out.append(f"  - No decision: {r['unlinked_reason']}")
    terms = {k["id"]: k["term"] for k in c.get("concepts", []) if "id" in k}
    uses = [f"- `{d['id']}` {d['title']} uses {terms[u['concept']]}: {u['because']}"
            for d in decisions for u in d.get("uses", [])]
    if uses:
        out += ["", "**Decisions and the concepts they use:**", ""] + uses
    titles = {d["id"]: d["title"] for d in decisions}
    out += ["", "**Results and the decisions they support:**", ""]
    for r in c.get("results", []):
        ids = so_ids(r)
        if ids:
            out.append(f"- {r['title']} → " + ", ".join(f"`{i}` {titles[i]}" for i in ids))
        elif r.get("so_none_reason"):
            out.append(f"- {r['title']} → no decision: {r['so_none_reason']}")
    return out + [""]


def _phased_flow(c):
    """The flow grouped by phase, numbered on across phases; each step with its output,
    date, decision and evidence commits, and milestones marked [MILESTONE]."""
    flow = c["flow"]
    titles = {d["id"]: d["title"] for d in c.get("decisions", [])}
    phases = flow_phases(flow)
    marks = [(n, s) for n, s in enumerate(flow, 1) if s.get("milestone")]
    summary = (f"{plural(len(flow), 'step')} in {plural(len(phases), 'phase')}, "
               f"{plural(len(marks), 'milestone')}.")
    milestones = "; ".join(f"{n}. {s['label']} ({s['when']})" for n, s in marks)
    out = [summary, "", f"Milestones: {milestones}."]
    for i, (name, steps) in enumerate(phases, 1):
        out += ["", f"### Phase {i} of {len(phases)}: {name} ({plural(len(steps), 'step')})",
                ""]
        for n, s in steps:
            mark = " [MILESTONE]" if s.get("milestone") else ""
            out.append(f"{n}. **{s['label']}**{mark}: {s['detail']}")
            if s.get("output"):
                out.append(f"   - Output: {s['output']}")
            if s.get("when"):
                out.append(f"   - When: {s['when']}")
            if s.get("decision"):
                out.append(f"   - Decision: `{s['decision']}` {titles[s['decision']]}")
            if s.get("evidence"):
                out.append("   - Evidence: " + "; ".join(_commit(e) for e in s["evidence"]))
    return out


def _commit(e):
    """'abc1234 in ~/projects/x (note)': the repo only when it is not this one."""
    repo = f" in {e['repo']}" if e.get("repo") else ""
    note = f" ({e['note']})" if e.get("note") else ""
    return f"{e['commit']}{repo}{note}"


def _axes_line(ch):
    """'- Axes: x is <x_label> (log scale); y is <y_label> (<unit>)[; right y is ...]
    [; log y]'."""
    x = ch["x_label"] + (" (log scale)" if ch.get("x_log") else "")
    unit = f" ({ch['unit']})" if ch["unit"] else ""
    line = f"- Axes: x is {x}; y is {ch['y_label']}{unit}"
    if ch.get("y_axes") == "dual":
        line += f"; right y is {ch['y2_label']} ({ch.get('y2_unit', ch['unit'])})"
    if ch.get("y_log"):
        line += "; log y"
    return line


def _refs_lines(ch):
    out = []
    for r in ch.get("refs", []):
        at = f"x = {r['x']}" if "x" in r else f"y = {r['y']} {ch['unit']}".rstrip()
        out.append(f"- Reference: {r['label']} at {at}")
    return out


def _xy_lines(ch):
    """The axes, then each series as 'x: y' pairs (whiskers as '(lo to hi)'), its bands,
    reference lines and note."""
    out = [_axes_line(ch)]
    for s in ch["series"]:
        tags = [t for t in (s.get("style") if s.get("style", "line") != "line" else None,
                            f"right axis, {ch.get('y2_unit', ch['unit'])}"
                            if s.get("axis") == "right" else None) if t]
        head = s["name"] + (f" ({', '.join(tags)})" if tags else "")
        pairs = ", ".join(f"{p['x']}: {p['y']}" + (f" ({p.get('lo', p['y'])} to "
                                                   f"{p.get('hi', p['y'])})"
                                                   if "lo" in p or "hi" in p else "")
                          for p in s["points"])
        out.append(f"- {head}: {pairs}")
    for b in ch.get("bands", []):
        out.append(f"- Band: {b['label']}, {b['y_lo']} to {b['y_hi']} {ch['unit']}".rstrip())
    out += _refs_lines(ch)
    if ch.get("note"):
        out.append(f"- Note: {ch['note']}")
    return out


def _scatter_lines(ch):
    """The axes, then each group's points as 'x: y' pairs (equal points once, with their
    count: '880: 14.44 ×19'; a label in brackets), the frontier, refs and note."""
    out = [_axes_line(ch)]
    for g in ch["groups"]:
        spots = {}
        for p in g["points"]:
            e = spots.setdefault((p["x"], p["y"]), [0, None])
            e[0] += 1
            e[1] = e[1] or p.get("label")
        pairs = ", ".join(f"{x}: {y}" + (f" \u00d7{n}" if n > 1 else "")
                          + (f" ({label})" if label else "")
                          for (x, y), (n, label) in spots.items())
        head = g["name"] + (f" ({g['marker']})" if g.get("marker") else "")
        out.append(f"- {head}: {pairs}")
    if ch.get("frontier"):
        fr = ch["frontier"]
        out.append(f"- Frontier, {fr['name']} (lower-left is better): "
                   + ", ".join(f"{p['x']}: {p['y']}" for p in fr["points"]))
    out += _refs_lines(ch)
    if ch.get("note"):
        out.append(f"- Note: {ch['note']}")
    return out


def _sequence_lines(v):
    """The participants, then the steps as a numbered list; a gap is an indented line."""
    out = [f"- **{p['label']}**" + (f": {p['sub']}" if p.get("sub") else "")
           for p in v["participants"]]
    names = {p["id"]: p["label"] for p in v["participants"]}
    out.append("")
    for s, n in zip(v["steps"], numbered(v["steps"])):
        out.append(f"{n}. {step_line(s, names)}" if n else f"   {step_line(s, names)}")
    return out + [""]


def _bullets(items):
    return "\n".join(f"- {i}" for i in items)


def render_brief(c: dict) -> str:
    c = resolve_links(c, "brief")
    out = [f"# {c['title']}: chat brief", ""]
    how = ("Paste this whole file into an AI chat, then paste the prompt at the end (it is "
           "already the last section). Ask clarifying questions about anything below. "
           f"About {c['minutes']} minutes to study.")
    out += ["## How to use this brief", "", how, ""]
    if c.get("prereqs"):
        out += ["Read first: " + ", ".join(f"{p['label']} ({p['unit'].upper()})"
                                           for p in c["prereqs"]) + ".", ""]
    if c["kind"] == "artifact":
        out += ["## Why it exists", "", f"**Question:** {c['question']}", "",
                "**Requirements that drove everything:**", ""]
        out += [f"- {_sentence(r['text'])} *Why:* {r['why']}" for r in c["requirements"]] + [""]
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
        out += ["## System views (C4)" if c["kind"] == "artifact" else "## Views", ""]
        for v in c["views"]:
            out += [f"### {v['title']} ({v['level']})", "", v["caption"], ""]
            if v.get("style") == "sequence":
                out += _sequence_lines(v)
                continue
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
    out += _relationships(c)
    if c.get("flow"):
        out += ["## Implementation flow", ""]
        if phased(c):
            out += _phased_flow(c)
        else:
            out += [f"{i}. **{s['label']}**: {s['detail']}" for i, s in enumerate(c["flow"], 1)]
        out.append("")
    if c.get("results"):
        out += ["## Results as meaning", ""]
        for r in c["results"]:
            out += [f"### {r['title']}", "", f"- Axis: {r['axis']}", f"- Read it as: {r['read_as']}"]
            if r.get("arithmetic"):
                out.append(f"- How it is computed: {r['arithmetic']}")
            ch = r["chart"]
            if ch["type"] == "stacked_bars":
                for b in ch["bars"]:
                    parts = ", ".join(f"{s['name']} {s['value']}" for s in b["segments"])
                    out.append(f"- {b['label']}: {parts} ({ch['unit']})")
                for g in ch.get("merge", []):
                    out.append(f"- Drawn as one segment, {g['label']}: " + " + ".join(g["names"]))
                if ch.get("ghost"):
                    g = ch["ghost"]
                    src = next(b for b in ch["bars"] if b["label"] == g["from_bar"])
                    value = next(v for n, v, _ in merged_segments(ch, src) if n == g["segment"])
                    out.append(f"- On bar {g['on_bar']}, a dashed outline shows where "
                               f"{g['segment']} sat in {g['from_bar']} ({_num(value)} {ch['unit']})")
                for d in ch.get("deltas", []):
                    out.append(f"- Changed {d['between']}: {d['text']}")
            elif ch["type"] == "percentiles":
                for row in ch["rows"]:
                    vals = ", ".join(f"{v['name']} {v['value']}" for v in row["values"])
                    m = row.get("max_label")
                    tail = f"; {m['text']} {m['value']} {ch['unit']}" if m else ""
                    out.append(f"- {row['label']}: {vals} ({ch['unit']}){tail}")
                if ch.get("note"):
                    out.append(f"- Note: {ch['note']}")
            elif ch["type"] == "xy":
                out += _xy_lines(ch)
            elif ch["type"] == "scatter":
                out += _scatter_lines(ch)
            elif ch["type"] == "interval":
                for row in ch["rows"]:
                    out.append(f"- {row['label']}: {row['estimate']} {ch['unit']} "
                               f"(interval {row['low']} to {row['high']})")
            else:
                for i in ch["items"]:
                    out.append(f"- {i['label']}: {i['value']} {ch['unit']}")
            ids = so_ids(r)
            if len(ids) == 1:
                out.append(f"- So: see decision `{ids[0]}`")
            elif ids:
                out.append("- So: see decisions " + ", ".join(f"`{i}`" for i in ids))
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
    out += ["", "Sources: see the page", ""]
    out += ["## Interview mode (paste this to an AI chat)", "", INTERVIEW_PROMPT]
    return "\n".join(out)
