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
    out += ["", "## Sources", ""]
    out += [f"- `{s['file']}`: {s['section']}" for s in c["sources"]]
    out += ["", "## Interview mode (paste this to an AI chat)", "", INTERVIEW_PROMPT]
    return "\n".join(out)
