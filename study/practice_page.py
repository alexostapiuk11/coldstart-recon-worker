"""The practice page: one self-contained HTML file per unit that has a practice.json.

Same shape as the study page (study.page): the page's colour tokens and dark mode, one
<style>, the body, one <script>, no external assets, so the same publish extraction works.
Every answer sits behind a <details>; the page reads fully without scripts. The script only
runs the calculator (study.calc.CALC_JS) and the pills bar's scroll fade.
"""

from __future__ import annotations

from study.calc import CALC_JS
from study.page import NAV_JS, TOKENS_CSS
from study.practice import calculator_defaults, link_context, num_str, review_target
from study.text import esc, inline, resolve_links

CSS = TOKENS_CSS + """*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,sans-serif;
overflow-wrap:break-word}
main{max-width:980px;margin:0 auto;padding:0 clamp(16px,4vw,40px) 64px}
header.hero{padding:32px 0 8px}
.kicker{color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.06em}
h1{font-size:28px;line-height:1.2;margin:6px 0 8px}
h2{font-size:21px;margin:0 0 8px}
h3{font-size:16px;margin:12px 0 4px}
p{margin:6px 0}
.forunit{color:var(--muted);font-size:17px;margin:0 0 6px}
.why{color:var(--muted);font-size:15px}
nav.pills{position:sticky;top:env(safe-area-inset-top,0px);background:var(--bg);padding:8px 0;
display:flex;gap:6px;flex-wrap:wrap;z-index:2;border-bottom:1px solid var(--line)}
nav.pills a{padding:3px 10px;border:1px solid var(--line);border-radius:99px;
color:var(--fg);text-decoration:none;font-size:13px}
section{margin-top:34px;scroll-margin-top:64px}
.card[id]{scroll-margin-top:64px}
a{color:var(--accent)}
ul,ol{margin:6px 0;padding-left:22px}li{margin:3px 0}
code{font-size:.92em;background:var(--soft);padding:1px 5px;border-radius:4px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:12px 16px;margin:10px 0}
.card h3:first-child{margin-top:0}
.code{display:inline-block;font-size:12px;font-weight:700;line-height:1.5;color:var(--accent);
border:1px solid var(--accent);border-radius:5px;padding:0 5px;margin-right:8px;
vertical-align:2px;font-variant-numeric:tabular-nums}
.q{font-size:17px;margin:4px 0 8px}
.dn{color:var(--muted);font-size:13px;font-weight:600;text-transform:uppercase;
letter-spacing:.05em}
details{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 12px;
margin:6px 0}
details>summary{cursor:pointer;font-weight:600}
details[open]>summary{margin-bottom:4px}
.card>details:first-of-type{margin-top:8px}
details.redflag{border-color:var(--warn);background:var(--warnsoft)}
details.redflag>summary{color:var(--warn)}
.miss{color:var(--muted);font-size:15px}
.badge{display:inline-block;font-size:12px;font-weight:700;letter-spacing:.05em;
text-transform:uppercase;border:1.5px solid currentColor;border-radius:99px;padding:1px 10px}
.cost-none{color:var(--ok)}.cost-local{color:var(--accent)}.cost-gpu{color:var(--warn)}
.cost-paid{background:var(--warn);border-color:var(--warn);color:var(--bg)}
.lab-top{margin:0 0 6px}
.rgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr));
gap:10px;align-items:start}
.rgrid details{margin:0;background:var(--card)}
.rcard>summary{font-weight:500}
.tag{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.06em;
text-transform:uppercase;color:var(--muted);border:1px solid var(--line);border-radius:4px;
padding:0 6px;margin-right:6px;vertical-align:1px}
.drawmark{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.06em;
text-transform:uppercase;color:var(--accent);border:1px solid var(--accent);border-radius:4px;
padding:0 6px;margin-left:6px;vertical-align:1px}
.rcard.draw{border-style:dashed;border-color:var(--accent)}
.rback{margin-top:6px;padding-top:6px;border-top:1px solid var(--line)}
.sched{list-style:none;padding:0}
.sched li{display:grid;grid-template-columns:150px 1fr;gap:10px;padding:8px 0;
border-top:1px solid var(--line)}
.sched li:first-child{border-top:0}
.sched b{color:var(--muted)}
.callout{border-left:4px solid var(--accent);padding:6px 12px;background:var(--soft);
border-radius:0 8px 8px 0;margin:8px 0}
@media (min-width:1100px){body{font-size:17px}h1{font-size:34px}h2{font-size:24px}}
@media (max-width:600px){h1{font-size:24px}.q{font-size:16px}
.sched li{grid-template-columns:1fr;gap:0}
nav.pills{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none;-webkit-overflow-scrolling:touch;
--fadeL:#000;--fadeR:transparent;
-webkit-mask-image:linear-gradient(#000,#000),linear-gradient(to right,var(--fadeL),#000 36px,#000 calc(100% - 36px),var(--fadeR));
mask-image:linear-gradient(#000,#000),linear-gradient(to right,var(--fadeL),#000 36px,#000 calc(100% - 36px),var(--fadeR));
-webkit-mask-size:100% 1px,100% 100%;mask-size:100% 1px,100% 100%;
-webkit-mask-position:0 100%,0 0;mask-position:0 100%,0 0;-webkit-mask-repeat:no-repeat;mask-repeat:no-repeat}
nav.pills[data-more=""]{-webkit-mask-image:none;mask-image:none}
nav.pills[data-more~="left"]{--fadeL:transparent}nav.pills[data-more="left"]{--fadeR:#000}
nav.pills::after{content:"";flex:none;width:32px}
nav.pills::-webkit-scrollbar{display:none}nav.pills a{flex:none}}
"""

# The calculator; shipped only on a page that has one.
CALC_CSS = """
.calc-row{display:grid;grid-template-columns:minmax(0,1.2fr) 130px minmax(0,1.6fr);gap:6px 14px;
align-items:center;padding:9px 0;border-top:1px solid var(--line)}
.calc-row:first-of-type{border-top:0}
.calc-row label{font-weight:600}
.calc-unit{color:var(--muted);font-size:13px;font-weight:400;margin-left:4px}
.calc-row input[type=number]{font:inherit;width:100%;min-height:40px;padding:6px 8px;
border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg);
font-variant-numeric:tabular-nums}
.calc-row input[type=number]:focus-visible,.calc-reset:focus-visible{outline:3px solid var(--accent);
outline-offset:2px}
.calc-row input[type=range]{width:100%;min-height:32px;accent-color:var(--accent)}
.calc-row input:disabled{opacity:.55}
.calc-outs{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr));
gap:10px;margin:12px 0 4px}
.calc-out{background:var(--soft);border:1px solid var(--line);border-radius:8px;padding:8px 12px}
.calc-ol{display:block;color:var(--muted);font-size:13px;font-weight:600;
text-transform:uppercase;letter-spacing:.04em}
.calc-ov{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.25}
.calc-ov output{overflow-wrap:anywhere}
.calc-nojs{color:var(--muted);font-size:14px;margin:8px 0 0}
.calc-js .calc-nojs{display:none}
.calc-reset{font:inherit;font-size:14px;color:var(--fg);background:var(--card);
border:1px solid var(--line);border-radius:8px;padding:6px 14px;min-height:36px;cursor:pointer}
.calc-reset[hidden]{display:none}
.calc-reset:hover{background:var(--soft);border-color:var(--accent)}
@media (max-width:600px){.calc-row{grid-template-columns:110px minmax(0,1fr)}
.calc-row label{grid-column:1/-1}}
"""

CALC_WIRING_JS = """
for (const g of document.querySelectorAll('[data-calc]')) {
  const nums = [...g.querySelectorAll('input[type=number]')];
  const outs = [...g.querySelectorAll('output[data-expr]')];
  const trees = outs.map(o => { try { return calcParse(o.dataset.expr); } catch (e) { return null; } });
  const slider = n => g.querySelector('input[type=range][data-for="' + n.dataset.id + '"]');
  const run = () => {
    const vars = {};
    nums.forEach(n => { vars[n.dataset.id] = n.value.trim() === '' ? NaN : Number(n.value); });
    const ok = Object.values(vars).every(Number.isFinite);
    outs.forEach((o, i) => {
      let text = 'n/a';
      try { if (ok && trees[i]) text = calcFmt(calcEval(trees[i], vars), +o.dataset.digits); }
      catch (e) { /* stays n/a */ }
      o.textContent = text;
    });
  };
  nums.forEach(n => {
    const r = slider(n);
    n.addEventListener('input', () => {
      if (r && n.value.trim() !== '' && Number.isFinite(Number(n.value))) r.value = n.value;
      run();
    });
    if (r) r.addEventListener('input', () => { n.value = r.value; run(); });
  });
  g.querySelector('.calc-reset').addEventListener('click', () => {
    nums.forEach(n => { n.value = n.defaultValue; const r = slider(n); if (r) r.value = r.defaultValue; });
    run();
  });
  g.querySelectorAll('input').forEach(i => { i.disabled = false; });
  g.querySelector('.calc-reset').hidden = false;
  g.classList.add('calc-js');
  run();
}
"""

COST_WORDS = {"none": "No cost", "local": "Runs on your machine", "gpu": "Needs a GPU",
              "paid": "Paid API calls"}


def _items(tag: str, texts: list[str]) -> str:
    return f"<{tag}>" + "".join(f"<li>{inline(t)}</li>" for t in texts) + f"</{tag}>"


def _objectives(p):
    return (f'<section id="objectives"><h2>Objectives</h2>{_items("ul", p["objectives"])}'
            "</section>")


def _check(p, unit, load_unit):
    cards = []
    for i, it in enumerate(p["prereq_check"], 1):
        _, term, href = review_target(it["review"], unit, load_unit)
        cards.append(
            f'<div class="card pq"><p class="q"><span class="code">{i}</span>{inline(it["q"])}'
            f'</p><details><summary>Show the answer</summary><p>{inline(it["a"])}</p>'
            f'<p class="miss">If you missed it, review <a href="{esc(href)}">{esc(term)}</a>.'
            "</p></details></div>")
    return ('<section id="check"><h2>Check yourself first</h2>'
            '<p class="why">Three questions the study page prepared you for. Answer out loud, '
            f'then open.</p>{"".join(cards)}</section>')


def _estimation(p):
    cards = []
    for i, it in enumerate(p["estimation"], 1):
        cards.append(
            f'<div class="card est" id="est-{i}"><h3>{inline(it["title"])}</h3>'
            f'<p>{inline(it["problem"])}</p><details><summary>Worked answer</summary>'
            f'{_items("ol", it["steps"])}<p><b>Answer.</b> {inline(it["answer"])}</p>'
            "</details></div>")
    return ('<section id="estimation"><h2>Estimation drills</h2>'
            '<p class="why">Do the arithmetic on paper first, then open the worked steps.</p>'
            f'{"".join(cards)}</section>')


def _drills(p):
    n = len(p["drills"])
    cards = []
    for i, it in enumerate(p["drills"], 1):
        cards.append(
            f'<div class="card drill" id="drill-{i}"><div class="dn">Drill {i} of {n}</div>'
            f'<p class="q">{inline(it["q"])}</p>'
            f'<details><summary>Model answer</summary><p>{inline(it["a"])}</p></details>'
            '<details class="redflag"><summary>Red-flag answer</summary>'
            f'<p>{inline(it["red_flag"])}</p></details></div>')
    return ('<section id="drills"><h2>Deep-dive drill</h2>'
            '<p class="why">Ordered easy to hard. Answer out loud, open the model answer, then '
            'the red-flag answer: the tempting reply that sounds right and is not.</p>'
            f'{"".join(cards)}</section>')


def _scenario(p):
    sc = p["scenario"]
    return ('<section id="scenario"><h2>Design scenario</h2><div class="card">'
            f'<p class="q">{inline(sc["prompt"])}</p>'
            '<details><summary>Outline of a strong answer</summary>'
            f'{_items("ol", sc["outline"])}</details>'
            '<details class="redflag"><summary>Pitfalls to check your answer against</summary>'
            f'{_items("ul", sc["pitfalls"])}</details></div></section>')


def _lab(p):
    lab = p["lab"]
    note = f'<p class="why">{inline(lab["note"])}</p>' if lab.get("note") else ""
    return (
        '<section id="lab"><h2>Lab</h2><div class="card lab"><div class="lab-top">'
        f'<span class="badge cost-{lab["cost"]}">{COST_WORDS[lab["cost"]]}</span></div>'
        f'<p><b>Goal.</b> {inline(lab["goal"])}</p>{note}'
        f'<h3>Setup</h3>{_items("ul", lab["setup"])}'
        f'<h3>Steps</h3>{_items("ol", lab["steps"])}'
        f'<h3>Record</h3>{_items("ul", lab["metrics"])}'
        '<details><summary>Expected result and what it shows</summary>'
        f'<p><b>Expected.</b> {inline(lab["expected"])}</p>'
        f'<p><b>Shows.</b> {inline(lab["demonstrates"])}</p></details></div></section>')


def _calculator(p):
    calc = p["calculator"]
    rows = []
    for it in calc["inputs"]:
        unit = f'<span class="calc-unit">{esc(it["unit"])}</span>' if it.get("unit") else ""
        value, lo, hi = (num_str(it[k]) for k in ("value", "min", "max"))
        rows.append(
            f'<div class="calc-row"><label for="calc-{esc(it["id"])}">{esc(it["label"])}'
            f'{unit}</label><input type="number" id="calc-{esc(it["id"])}" '
            f'data-id="{esc(it["id"])}" value="{value}" min="{lo}" max="{hi}" step="any" '
            f'disabled><input type="range" data-for="{esc(it["id"])}" value="{value}" '
            f'min="{lo}" max="{hi}" step="{num_str(it["step"])}" disabled '
            f'aria-label="{esc(it["label"])}"></div>')
    outs = []
    for o, (label, text, unit) in zip(calc["outputs"], calculator_defaults(calc)):
        u = f' <span class="calc-unit">{esc(unit)}</span>' if unit else ""
        outs.append(
            f'<div class="calc-out"><span class="calc-ol">{esc(label)}</span>'
            f'<span class="calc-ov"><output data-expr="{esc(o["expr"])}" '
            f'data-digits="{o["digits"]}">{esc(text)}</output>{u}</span></div>')
    note = f'<p class="why">{inline(calc["note"])}</p>' if calc.get("note") else ""
    return (
        f'<section id="calculator"><h2>{esc(calc["title"])}</h2>{note}'
        f'<div class="card" data-calc>{"".join(rows)}'
        f'<div class="calc-outs" aria-live="polite">{"".join(outs)}</div>'
        '<p class="calc-nojs">JavaScript is off: these are the values at the default inputs.'
        '</p><p><button type="button" class="calc-reset" hidden>Reset to defaults</button></p>'
        "</div></section>")


def _cards(p):
    cards = []
    for it in p["cards"]:
        draw = it.get("draw")
        mark = '<span class="drawmark">Draw it</span>' if draw else ""
        cards.append(
            f'<details class="rcard{" draw" if draw else ""}"><summary>'
            f'<span class="tag">{esc(it["tag"])}</span>{inline(it["front"])}{mark}</summary>'
            f'<div class="rback">{inline(it["back"])}</div></details>')
    return ('<section id="cards"><h2>Recall cards</h2>'
            '<p class="why">Read the front, say the back, then open. A card marked "Draw it" '
            f'asks you to sketch first.</p><div class="rgrid">{"".join(cards)}</div></section>')


def _schedule(p):
    rows = "".join(f'<li><b>{esc(s["when"])}</b><span>{inline(s["test"])}</span></li>'
                   for s in p["schedule"])
    return (f'<section id="schedule"><h2>Review schedule</h2><ul class="sched">{rows}</ul>'
            "</section>")


def _assumptions(p):
    rows = [f'<li><code>{esc(a["value"])}</code> {inline(a["why"])}</li>'
            for a in p.get("assumed_numbers", [])]
    rows += [f'<li><code>{esc(d["value"])}</code> worked out: {inline(d["how"])}</li>'
             for d in p.get("derived_numbers", [])]
    n = len(rows)
    return ('<section id="assumptions"><details><summary>Numbers assumed or worked out on '
            f'this page, {n}</summary><p class="why">None of these comes from the study '
            f'page\'s sources.</p><ul>{"".join(rows)}</ul></details></section>')


def render_practice_page(p: dict, unit: dict, load_unit=None) -> str:
    p = resolve_links(link_context(p, unit), "page", own_url="page.html")
    sections, nav = [], []

    def add(sid, label, html):
        sections.append(html)
        nav.append(f'<a href="#{sid}">{label}</a>')

    add("objectives", "Objectives", _objectives(p))
    add("check", "Check first", _check(p, unit, load_unit))
    add("estimation", "Estimation", _estimation(p))
    add("drills", "Drills", _drills(p))
    add("scenario", "Scenario", _scenario(p))
    add("lab", "Lab", _lab(p))
    css, js = CSS, NAV_JS
    if p.get("calculator"):
        add("calculator", "Calculator", _calculator(p))
        css, js = css + CALC_CSS, js + CALC_JS + CALC_WIRING_JS
    add("cards", "Cards", _cards(p))
    add("schedule", "Schedule", _schedule(p))
    if p.get("assumed_numbers") or p.get("derived_numbers"):
        add("assumptions", "Assumptions", _assumptions(p))
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{esc(p["title"])}</title><style>{css}</style></head><body><main>'
        f'<header class="hero"><div class="kicker">Practice page · about {p["minutes"]} min'
        f'</div><h1>{esc(p["title"])}</h1>'
        f'<p class="forunit">Practice for: {esc(unit["title"])}</p>'
        '<p class="why">Try every question before you open its answer. The study page is the '
        'reading; this page is the doing.</p></header>'
        f'<nav class="pills">{"".join(nav)}</nav>{"".join(sections)}</main>'
        f'<script>{js}</script></body></html>')
