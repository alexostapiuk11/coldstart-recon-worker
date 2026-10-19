"""The chat brief: a unit's facts as compact markdown, ending in the interview prompt."""

from __future__ import annotations

from study.schema import so_ids

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
