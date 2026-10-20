"""The practice brief: a unit's drills, scenario and cards as compact markdown for an AI chat.

Every answer is marked KEY (or RED FLAG): the questioner sees it, the learner must not until
they have answered. The last section is the drill-mode prompt.
"""

from __future__ import annotations

from study.practice import calculator_defaults, link_context, num_str, review_target
from study.practice_page import COST_WORDS
from study.text import resolve_links

DRILL_PROMPT = """\
You are my drill coach for this practice set. The brief above is the only ground truth. Lines
marked KEY and RED FLAG are for you: never show them before I have answered.

Settings (I may change these at any time):
- SECTION: all (default) | check | estimation | drills | scenario | cards
- PACE: one question at a time

Rules:
1. Ask one question at a time, in the order of the brief unless I pick a section. Start with
   "Check yourself first", then the drills from easy to hard. Wait for my answer.
2. Grade against the KEY: say what I got, what I missed (quote the KEY point), and score me
   0 (miss), 1 (partial) or 2 (solid). Five lines at most.
3. If my answer falls into the RED FLAG, name it ("that is the red-flag answer: ...") and ask
   me to try again before moving on.
4. Do not add facts the brief lacks. If I ask beyond it, say "the brief does not say".
5. Estimation: let me show my steps before you reveal the KEY steps. Accept an answer within a
   factor of 2 if the steps are sound.
6. Scenario: let me talk it through; then check my answer against the KEY outline and pitfalls.
7. Cards: show only the front. For a [draw] card, ask me to describe my sketch in words, then
   compare it with the KEY.
8. Keep a list of everything I scored 0 or 1. Repeat those items later in the session, and at
   the end tell me which to re-test in each slot of "Review schedule".
9. At the end give a score table and the three items to re-test first.
10. Start now with the first question.
"""


def _bullets(items):
    return [f"- {i}" for i in items]


def _numbered(items):
    return [f"{n}. {i}" for n, i in enumerate(items, 1)]


def _review(review, unit, load_unit):
    other, term, _ = review_target(review, unit, load_unit)
    if other == unit["id"]:
        return term
    return f"{term} ({other.upper()}: {review.partition(':')[2]})"


def render_practice_brief(p: dict, unit: dict, load_unit=None) -> str:
    p = resolve_links(link_context(p, unit), "brief")
    out = [f"# {p['title']}: practice brief", ""]
    how = ("Paste this whole file into an AI chat. The last section is the prompt that makes "
           "the chat quiz you; lines marked KEY and RED FLAG are the answers, hidden from you "
           f"until you have tried. Practice for: {unit['title']}. About {p['minutes']} "
           "minutes.")
    out += ["## How to use this brief", "", how, ""]
    out += ["## Objectives", ""] + _bullets(p["objectives"]) + [""]

    out += ["## Check yourself first", ""]
    for i, it in enumerate(p["prereq_check"], 1):
        out += [f"### Check {i}", "", f"Q: {it['q']}", f"KEY: {it['a']}",
                f"If missed, review: {_review(it['review'], unit, load_unit)}", ""]

    out += ["## Estimation drills", ""]
    for i, it in enumerate(p["estimation"], 1):
        out += [f"### Estimate {i}: {it['title']}", "", f"Problem: {it['problem']}", "",
                "KEY steps:", ""] + _numbered(it["steps"]) + ["", f"KEY answer: {it['answer']}", ""]

    out += ["## Deep-dive drills", "", "Ordered easy to hard.", ""]
    n = len(p["drills"])
    for i, it in enumerate(p["drills"], 1):
        out += [f"### Drill {i} of {n}", "", f"Q: {it['q']}", f"KEY: {it['a']}",
                f"RED FLAG: {it['red_flag']}", ""]

    sc = p["scenario"]
    out += ["## Design scenario", "", f"Prompt: {sc['prompt']}", "", "KEY outline:", ""]
    out += _numbered(sc["outline"]) + ["", "KEY pitfalls:", ""] + _bullets(sc["pitfalls"]) + [""]

    lab = p["lab"]
    out += ["## Lab", "", f"Cost: {COST_WORDS[lab['cost']].lower()}", f"Goal: {lab['goal']}"]
    if lab.get("note"):
        out.append(f"Note: {lab['note']}")
    out += ["", "Setup:", ""] + _bullets(lab["setup"]) + ["", "Steps:", ""]
    out += _numbered(lab["steps"]) + ["", "Record:", ""] + _bullets(lab["metrics"])
    out += ["", f"KEY expected result: {lab['expected']}",
            f"KEY what it shows: {lab['demonstrates']}", ""]

    if p.get("calculator"):
        calc = p["calculator"]
        out += ["## Calculator", "", f"{calc['title']}"
                + (f" {calc['note']}" if calc.get("note") else ""), "", "Inputs (default, range):",
                ""]
        for it in calc["inputs"]:
            unit_ = f" {it['unit']}" if it.get("unit") else ""
            out.append(f"- {it['label']}: {num_str(it['value'])}{unit_} "
                       f"(range {num_str(it['min'])} to {num_str(it['max'])})")
        out += ["", "Outputs at the defaults:", ""]
        for o, (label, text, unit_) in zip(calc["outputs"], calculator_defaults(calc)):
            out.append(f"- {label} = {text}{' ' + unit_ if unit_ else ''}  [{o['expr']}]")
        out.append("")

    out += ["## Recall cards", ""]
    for it in p["cards"]:
        tag = f"{it['tag']}, draw" if it.get("draw") else it["tag"]
        mark = f"[{tag}]" if not it.get("draw") else f"[{it['tag']}] [draw]"
        out.append(f"- {mark} {it['front']} -> KEY: {it['back']}")
    out.append("")

    out += ["## Review schedule", ""] + [f"- {s['when']}: {s['test']}" for s in p["schedule"]]
    out.append("")

    if p.get("assumed_numbers") or p.get("derived_numbers"):
        out += ["## Assumed numbers", "", "Not from the study page's sources:", ""]
        out += [f"- {a['value']}: {a['why']}" for a in p.get("assumed_numbers", [])]
        out += [f"- {d['value']}: worked out, {d['how']}" for d in p.get("derived_numbers", [])]
        out.append("")

    out += ["## Drill mode (paste this to an AI chat)", "", DRILL_PROMPT]
    return "\n".join(out)
