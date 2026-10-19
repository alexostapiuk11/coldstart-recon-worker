"""The study page: one self-contained HTML file per unit.

Sections appear in the spec's order; any section whose data is absent is skipped.
Everything is inline (CSS, SVG, a few lines of JS). The JS only switches tabs, and the
page reads fully without it.

Chart colours --c0..--c7 are the dataviz skill's validated categorical palette (light and
dark steps, fixed order). --t0..--t7 are the ink for a value printed inside a segment of
that colour: black or white, whichever clears 4.5:1 on the fill.
"""

from __future__ import annotations

from study.svg import chart_html, diagram_html
from study.text import esc, inline

CSS = """
:root{--bg:#fafaf7;--fg:#1d2330;--muted:#5b6475;--card:#fff;--line:#d9dce3;
--accent:#2f5fd0;--soft:#e8eefc;--warn:#b4540a;--warnsoft:#fdf0e3;--ok:#1f7a4d;
--c0:#2a78d6;--c1:#eb6834;--c2:#1baf7a;--c3:#eda100;--c4:#e87ba4;--c5:#008300;
--c6:#4a3aa7;--c7:#e34948;--t0:#000;--t1:#000;--t2:#000;--t3:#000;--t4:#000;
--t5:#fff;--t6:#fff;--t7:#000}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#14171f;
--fg:#e6e8ee;--muted:#9aa3b5;--card:#1c202b;--line:#323849;--accent:#7ea2ff;
--soft:#222b45;--warn:#f0a15e;--warnsoft:#33261a;--ok:#5fcf9a;--c0:#3987e5;--c1:#d95926;
--c2:#199e70;--c3:#c98500;--c4:#d55181;--c5:#008300;--c6:#9085e9;--c7:#e66767;
--t6:#000;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#14171f;--fg:#e6e8ee;--muted:#9aa3b5;--card:#1c202b;
--line:#323849;--accent:#7ea2ff;--soft:#222b45;--warn:#f0a15e;--warnsoft:#33261a;
--ok:#5fcf9a;--c0:#3987e5;--c1:#d95926;--c2:#199e70;--c3:#c98500;--c4:#d55181;
--c5:#008300;--c6:#9085e9;--c7:#e66767;--t6:#000;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,sans-serif}
main{max-width:1560px;margin:0 auto;padding:0 clamp(16px,4vw,56px) 64px}
header.hero{padding:32px 0 8px}
.kicker{color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.06em}
h1{font-size:28px;line-height:1.2;margin:6px 0 10px}
h2{font-size:21px;margin:0 0 12px}
h3{font-size:16px;margin:0 0 6px}
.lead{font-size:18px}
nav.pills{position:sticky;top:env(safe-area-inset-top,0px);background:var(--bg);padding:8px 0;display:flex;gap:6px;
flex-wrap:wrap;z-index:2;border-bottom:1px solid var(--line)}
nav.pills a{padding:3px 10px;border:1px solid var(--line);border-radius:99px;
color:var(--fg);text-decoration:none;font-size:13px}
section{margin-top:36px}
section,.card[id]{scroll-margin-top:64px}
a{color:var(--accent)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;margin:10px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,560px),1fr));gap:12px;align-items:start}
.grid2>.card{margin:0}
.grid>.card{margin:0}
.why{color:var(--muted);font-size:14px}
.row{margin:6px 0}.row b{display:inline-block;min-width:96px;margin-right:6px;color:var(--muted);
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
.elabel{font-size:11px;fill:var(--muted);paint-order:stroke;stroke:var(--card);stroke-width:4px}
.node rect{fill:var(--card);stroke:var(--accent);stroke-width:1.5}
.node.k-person rect{fill:var(--soft)}.node.k-external rect{stroke:var(--muted);
stroke-dasharray:4 3}.node.k-store rect{fill:var(--warnsoft);stroke:var(--warn)}
.node.k-focus rect{fill:var(--soft);stroke-width:2.5}
.nlabel{font-size:13px;font-weight:600;fill:var(--fg)}.nsub{font-size:11px;fill:var(--muted)}
.chart{width:100%;max-width:760px;height:auto;display:block}
.blabel{font-size:12px;fill:var(--fg);font-weight:600}.segtext{font-size:11px}
.btotal{font-size:12px;fill:var(--fg)}
.seg.s0,.chip.s0{fill:var(--c0);background:var(--c0)}
.seg.s1,.chip.s1{fill:var(--c1);background:var(--c1)}
.seg.s2,.chip.s2{fill:var(--c2);background:var(--c2)}
.seg.s3,.chip.s3{fill:var(--c3);background:var(--c3)}
.seg.s4,.chip.s4{fill:var(--c4);background:var(--c4)}
.seg.s5,.chip.s5{fill:var(--c5);background:var(--c5)}
.seg.s6,.chip.s6{fill:var(--c6);background:var(--c6)}
.seg.s7,.chip.s7{fill:var(--c7);background:var(--c7)}
.segtext.s0{fill:var(--t0)}.segtext.s1{fill:var(--t1)}.segtext.s2{fill:var(--t2)}
.segtext.s3{fill:var(--t3)}.segtext.s4{fill:var(--t4)}.segtext.s5{fill:var(--t5)}
.segtext.s6{fill:var(--t6)}.segtext.s7{fill:var(--t7)}
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
@media (min-width:1100px){body{font-size:18px}h1{font-size:36px}h2{font-size:26px}h3{font-size:18px}
.lead{font-size:21px}.why{font-size:16px}.row b{min-width:104px}}
@media (max-width:600px){.diagram{display:none}.diagram-text{display:block}
h1{font-size:24px}.lead{font-size:16px}
.blabel,.btotal{font-size:15px}.segtext{font-size:14px}}
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
    return (f'<section id="decisions"><h2>Core decisions</h2>'
            f'<div class="grid2">{"".join(cards)}</div></section>')


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
    return (f'<section id="results"><h2>Results, as meaning</h2>'
            f'<div class="grid2">{"".join(cards)}</div></section>')


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
