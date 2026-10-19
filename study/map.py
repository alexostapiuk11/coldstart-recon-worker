"""The relationship map: how requirements, decisions, results and concepts connect.

Rendered only for units whose requirements carry ids (see schema._relationships). Three
columns, left to right: what drove the work (requirements, then the key concepts as the
vocabulary), the decisions, and what came out (results). Every edge touches a decision,
so edges only run between adjacent columns, always left to right. Decisions and results
keep the content order (D1.., F1.. match the cards); requirements and concepts are each
ordered by the barycentre of the decisions they link to, which keeps crossings low
without any hand-written order. On a phone the columns stack in the same order:
requirements, concepts, decisions, results.

Each box shows its card's code and heading word for word (see _graph), wrapping to more
lines as needed rather than truncating.

Everything the reader sees is rendered here, escaped: the nodes, an edge element per
link, and per node a <template> with its side-panel text. The JS only draws the edge
curves from the laid-out boxes and toggles selection, so a link that is in the content
is in the HTML whether or not the JS runs.
"""

from __future__ import annotations

from study.links import link_index, req_label
from study.schema import so_ids
from study.text import esc, inline

KIND_NAME = {"req": "Requirement", "dec": "Decision", "res": "Result", "con": "Key concept"}
# A panel's link groups use the words of the card rows (page.py), in lane order.
GROUP_HEAD = {
    "req": {"dec": "Answered by"},
    "dec": {"req": "Serves", "con": "Uses", "res": "Seen in"},
    "res": {"dec": "Rests on"},
    "con": {"dec": "Used by"},
}
LANE_ORDER = ("req", "con", "dec", "res")

MAP_CSS = """
#map .mq{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);
border-radius:0 10px 10px 0;padding:10px 14px;margin:0 0 10px;font-size:1.05em;font-weight:600}
#map .mq-k{display:block;color:var(--muted);font-size:13px;font-weight:600;text-transform:uppercase;
letter-spacing:.06em}
.mlegend{display:flex;flex-wrap:wrap;gap:4px 18px;margin:0 0 14px;font-size:14px;color:var(--muted)}
.mlegend .msw{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;
vertical-align:-1px;background:var(--k)}
#map .req{--k:var(--c0)}#map .dec{--k:var(--c1)}#map .res{--k:var(--c2)}
#map .con{--k:var(--c6)}
.mnode,.mref,.mkind,.mhead,.mres-t,.mcon-t{--kt:color-mix(in srgb,var(--k) 62%,var(--fg));
--kb:color-mix(in srgb,var(--k) 14%,var(--card))}
.mmain{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:24px;align-items:start}
.mgrid{position:relative;display:grid;
grid-template-columns:minmax(0,1fr) 96px minmax(0,1fr) 96px minmax(0,1fr)}
.medges{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:visible}
.medge{fill:none;stroke:var(--muted);stroke-opacity:.6;stroke-width:1.6;
transition:opacity .15s,stroke-width .15s}
.medge.on{stroke:var(--fg);stroke-opacity:1;stroke-width:2.6}
.medges.has-sel .medge:not(.on){opacity:.12}
.mcol{position:relative;z-index:1;display:flex;flex-direction:column;min-width:0}
.mcol-left{grid-column:1}.mcol-dec{grid-column:3}.mcol-right{grid-column:5}
.mhead{font-size:14px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
margin:0 0 10px;color:var(--kt)}
.mhead.req{--k:var(--c0)}.mhead.con{--k:var(--c6);margin-top:22px}.mhead.dec{--k:var(--c1)}
.mhead.res{--k:var(--c2)}
.mhead .mpar{font-weight:400;text-transform:none;letter-spacing:0}
.mstack{display:flex;flex-direction:column;justify-content:space-around;gap:12px;flex:1}
.mcol-left .mstack{flex:none;justify-content:flex-start}
.mmapcol{min-width:0}.mlanes{color:var(--muted);font-size:14px;margin:12px 0 0}
.mnode{position:relative;display:block;width:100%;text-align:left;font:inherit;color:var(--fg);
background:var(--card);border:1px solid var(--line);border-left:5px solid var(--k);
border-radius:10px;padding:9px 12px;cursor:pointer;transition:opacity .15s,box-shadow .15s;
-webkit-tap-highlight-color:transparent}
.mnode:hover{background:var(--kb)}
.mnode:focus-visible,.mref:focus-visible,.mclear:focus-visible{outline:3px solid var(--accent);
outline-offset:2px}
.mcode{font-size:14px;font-weight:700;color:var(--kt);margin-right:6px;
font-variant-numeric:tabular-nums}
.mlab{font-size:16px;font-weight:600;line-height:1.3}
.mlinks{display:none;font-size:14px;color:var(--muted);margin-top:3px}
.mgrid.has-sel .mnode{opacity:.3}
.mgrid.has-sel .mnode.is-sel,.mgrid.has-sel .mnode.is-linked{opacity:1}
.mnode.is-linked{background:var(--kb);box-shadow:0 0 0 2px var(--k)}
.mnode.is-sel{background:var(--kb);box-shadow:0 0 0 3px var(--k),0 6px 18px rgba(0,0,0,.14)}
.mpanel{position:sticky;top:64px;background:var(--card);border:1px solid var(--line);
border-radius:12px;padding:14px 16px;max-height:calc(100vh - 80px);overflow:auto}
.mpanel-top{display:flex;justify-content:flex-end;margin:-4px 0 4px}
.mclear{font:inherit;font-size:14px;color:var(--fg);background:var(--card);
border:1px solid var(--line);border-radius:8px;padding:5px 10px;cursor:pointer;min-height:34px}
.mclear:disabled{opacity:.45;cursor:default}
.mkind{font-size:13px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;margin:0;
color:var(--kt)}
.mpanel h3{font-size:19px;line-height:1.25;margin:4px 0 8px}
.mpanel .mtext{margin:0 0 10px}
.mpanel .mnote{font-size:15px;color:var(--muted);border-left:3px solid var(--warn);
padding-left:10px;margin:0 0 10px}
.mpanel h4{font-size:13px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
color:var(--muted);margin:14px 0 6px}
.mpanel ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px}
.mref{font:inherit;text-align:left;width:100%;background:var(--bg);color:var(--fg);
border:1px solid var(--line);border-left:4px solid var(--k);border-radius:8px;padding:6px 10px;
cursor:pointer}
.mref:hover{border-color:var(--muted);border-left-color:var(--k)}
.mref .nm{display:block;font-size:15px;font-weight:600}
.mref .mwhy{display:block;font-size:14px;color:var(--muted);margin-top:2px}
.mpanel .mhint{color:var(--muted);font-size:15px;margin:0}
.mgo{font-size:14px}
.mtap{display:none}
@media (max-width:1199px) and (min-width:1000px){.mmain{grid-template-columns:minmax(0,1fr) 290px;
gap:20px}.mgrid{grid-template-columns:minmax(0,1fr) 60px minmax(0,1fr) 60px minmax(0,1fr)}
.mlab{font-size:15px}}
@media (max-width:999px){.mmain{grid-template-columns:minmax(0,1fr)}
.mgrid{grid-template-columns:minmax(0,1fr) 64px minmax(0,1fr) 64px minmax(0,1fr)}
.mlab{font-size:15px}
.mpanel{position:fixed;left:12px;right:12px;bottom:12px;top:auto;max-height:44vh;z-index:5;
box-shadow:0 -4px 24px rgba(0,0,0,.25);display:none}
#map.has-sel .mpanel{display:block}
.mpanel .mhome{display:none}#map .mtap{display:block;margin:-6px 0 12px;color:var(--muted);font-size:15px}}
@media (max-width:759px){.mlanes{display:none}
.mgrid{display:block}.medges{display:none}.mcol{margin-bottom:20px}.mstack{gap:8px}
.mlinks{display:block}.mlinks.none{font-style:italic}}
"""

MAP_JS = r"""
(() => {
  const grid = document.getElementById('mgrid');
  if (!grid) return;
  const section = document.getElementById('map'), svg = grid.querySelector('.medges');
  const panel = document.getElementById('mpanel'), body = panel.querySelector('.mpanel-body');
  const clearBtn = panel.querySelector('.mclear'), home = body.innerHTML;
  const nodes = new Map([...grid.querySelectorAll('.mnode')].map(b => [b.id, b]));
  const edges = [...svg.querySelectorAll('.medge')].map(p => ({ el: p, a: p.dataset.from, b: p.dataset.to }));
  const adj = new Map([...nodes.keys()].map(k => [k, new Set()]));
  edges.forEach(e => { adj.get(e.a).add(e.b); adj.get(e.b).add(e.a); });
  const sheet = () => matchMedia('(max-width: 999px)').matches;
  let sel = null;

  function draw() {
    if (getComputedStyle(svg).display === 'none') return;
    const m = grid.getBoundingClientRect();
    const R = new Map([...nodes].map(([id, el]) => {
      const r = el.getBoundingClientRect();
      return [id, { l: r.left - m.left, r: r.right - m.left, t: r.top - m.top,
                    b: r.bottom - m.top, cy: (r.top + r.bottom) / 2 - m.top }];
    }));
    // Spread each node's ports along its side, ordered by the far end's height, so
    // edges leaving one box do not cross each other.
    const ports = new Map();
    edges.forEach((e, i) => {
      [[e.a + '|out', e.b], [e.b + '|in', e.a]].forEach(([k, far]) => {
        if (!ports.has(k)) ports.set(k, []);
        ports.get(k).push([i, far]);
      });
    });
    const portY = new Map();
    ports.forEach((list, k) => {
      const [id, side] = k.split('|'), box = R.get(id);
      list.sort((p, q) => R.get(p[1]).cy - R.get(q[1]).cy);
      const span = Math.min((box.b - box.t) * 0.6, 10 * (list.length - 1));
      list.forEach(([i], j) => portY.set(i + side, box.cy - span / 2 +
        (list.length > 1 ? span * j / (list.length - 1) : span / 2)));
    });
    edges.forEach((e, i) => {
      const x1 = R.get(e.a).r, y1 = portY.get(i + 'out'), x2 = R.get(e.b).l, y2 = portY.get(i + 'in');
      const dx = (x2 - x1) / 2;
      e.el.setAttribute('d', `M${x1} ${y1} C${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`);
    });
  }

  function show(id) {
    if (!id) { body.innerHTML = home; return; }
    body.replaceChildren(document.getElementById('mp-' + id).content.cloneNode(true));
  }

  function apply() {
    const linked = sel ? adj.get(sel) : new Set();
    grid.classList.toggle('has-sel', !!sel);
    svg.classList.toggle('has-sel', !!sel);
    section.classList.toggle('has-sel', !!sel);
    nodes.forEach((el, id) => {
      el.classList.toggle('is-sel', id === sel);
      el.classList.toggle('is-linked', linked.has(id));
      el.setAttribute('aria-pressed', id === sel ? 'true' : 'false');
    });
    edges.forEach(e => e.el.classList.toggle('on', !!sel && (e.a === sel || e.b === sel)));
    clearBtn.disabled = !sel;
    show(sel);
    panel.scrollTop = 0;
  }

  function reveal(el) {
    // On a phone the sheet covers the lower part of the screen; keep the box above it.
    const r = el.getBoundingClientRect();
    if (sheet() && (r.bottom > innerHeight * 0.52 || r.top < 60)) {
      scrollBy({ top: r.top - innerHeight * 0.2, behavior: 'smooth' });
    } else if (!sheet()) {
      el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }

  function select(id) { sel = sel === id ? null : id; apply(); if (sel) reveal(nodes.get(sel)); }
  function clear() { const was = sel; sel = null; apply(); if (was) nodes.get(was).focus(); }

  nodes.forEach((el, id) => {
    el.addEventListener('click', () => select(id));
    const preview = () => { if (!sel && !sheet()) show(id); };
    const unpreview = () => { if (!sel && !sheet()) show(null); };
    el.addEventListener('mouseenter', preview); el.addEventListener('mouseleave', unpreview);
    el.addEventListener('focus', preview); el.addEventListener('blur', unpreview);
  });
  panel.addEventListener('click', e => {
    const b = e.target.closest('[data-go]');
    if (!b) return;
    sel = b.dataset.go; apply();
    const el = nodes.get(sel);
    reveal(el); el.focus({ preventScroll: true });
  });
  clearBtn.addEventListener('click', clear);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && sel) clear(); });
  // A sheet left open after scrolling away from the map would cover the rest of the page.
  new IntersectionObserver(es => es.forEach(en => {
    if (!en.isIntersecting && sel && sheet()) { sel = null; apply(); }
  })).observe(grid);
  new ResizeObserver(draw).observe(grid);
  addEventListener('resize', draw);
  apply();
  draw();
})();
"""


def has_map(c: dict) -> bool:
    return any("id" in r for r in c.get("requirements", []))


def barycentre_order(items: list, neighbours: dict) -> list:
    """Order items by the mean position of their neighbours in a fixed column.

    Items with no neighbours go last; ties keep the input order (Python's sort is
    stable), so the result is deterministic.
    """
    def key(item):
        ps = neighbours.get(item, [])
        return (0, sum(ps) / len(ps)) if ps else (1, 0.0)
    return sorted(items, key=key)


def _graph(c):
    """Nodes (dicts keyed by DOM id) and edges (left DOM id, right DOM id, because).

    A node's label is its card's heading word for word, under the card's code, so a box
    in the map and its card read the same. `short` is not used here.
    """
    ix = link_index(c)
    nodes = {}

    def add(dom, kind, code, ref, label, text, note=""):
        nodes[dom] = {"dom": dom, "kind": kind, "code": code, "ref": ref, "label": label,
                      "text": text, "note": note}

    req_dom, dec_dom, con_dom = {}, {}, {}
    for i, r in enumerate(c["requirements"]):
        req_dom[r["id"]] = f"m-r{i}"
        note = (f"No decision serves this requirement. {r['unlinked_reason']}"
                if r.get("unlinked_reason") else "")
        add(f"m-r{i}", "req", r["id"], r["id"], req_label(r), r["text"], note)
    for i, d in enumerate(c["decisions"]):
        dec_dom[d["id"]] = f"m-d{i}"
        add(f"m-d{i}", "dec", ix["dec_code"][d["id"]], d["id"], d["title"],
            d.get("why_short", ""))
    for i, r in enumerate(c.get("results", [])):
        note = (f"Supports no decision. {r['so_none_reason']}"
                if r.get("so_none_reason") else "")
        add(f"m-f{i}", "res", ix["res_code"][i], str(i), r["title"], r.get("takeaway", ""),
            note)
    for i, t in enumerate(k for k in c.get("concepts", []) if "id" in k):
        con_dom[t["id"]] = f"m-c{i}"
        add(f"m-c{i}", "con", ix["con_code"][t["id"]], t["id"], t["term"], t["plain"])

    edges = []
    for d in c["decisions"]:
        for s in d.get("serves", []):
            edges.append((req_dom[s["req"]], dec_dom[d["id"]], s["because"]))
        for u in d.get("uses", []):
            edges.append((con_dom[u["concept"]], dec_dom[d["id"]], u["because"]))
    for i, r in enumerate(c.get("results", [])):
        for d in so_ids(r):
            edges.append((dec_dom[d], f"m-f{i}", r.get("takeaway", "")))
    return nodes, edges


def _node_button(n, links):
    others = " · ".join(links)
    if others:
        line = f'<span class="mlinks">Links: {esc(others)}</span>'
    elif n["note"]:
        line = '<span class="mlinks none">No decision linked; select for why</span>'
    else:
        line = '<span class="mlinks none">No links</span>'
    count = f"{len(links)} link{'' if len(links) == 1 else 's'}"
    return (f'<button type="button" class="mnode {n["kind"]}" id="{n["dom"]}" '
            f'data-ref="{esc(n["ref"])}" aria-pressed="false" aria-controls="mpanel" '
            f'aria-label="{esc(KIND_NAME[n["kind"]])} {esc(n["code"])}: {esc(n["label"])}. '
            f'{count}.">'
            f'<span class="mcode">{esc(n["code"])}</span><span class="mlab">{esc(n["label"])}</span>'
            f'{line}</button>')


def _panel(n, linked, nodes):
    """The side-panel content for one node: its text, then its links grouped by kind."""
    kind = n["kind"]
    out = [f'<p class="mkind {kind}">{KIND_NAME[kind]} {esc(n["code"])}</p>',
           f'<h3>{esc(n["label"])}</h3>']
    if n["text"] and n["text"] != n["label"]:
        out.append(f'<p class="mtext">{inline(n["text"])}</p>')
    if n["note"]:
        out.append(f'<p class="mnote">{inline(n["note"])}</p>')
    for other_kind in LANE_ORDER:
        group = [(o, why) for o, why in linked if nodes[o]["kind"] == other_kind]
        if not group:
            continue
        items = []
        for o, why in group:
            on = nodes[o]
            why_html = f'<span class="mwhy">{inline(why)}</span>' if why else ""
            items.append(f'<li><button type="button" class="mref {on["kind"]}" data-go="{on["dom"]}">'
                         f'<span class="nm">{esc(on["code"])} · {esc(on["label"])}</span>'
                         f'{why_html}</button></li>')
        out.append(f'<h4>{GROUP_HEAD[kind][other_kind]}</h4><ul>{"".join(items)}</ul>')
    if kind == "dec":
        out.append(f'<p class="mgo"><a href="#d-{esc(n["ref"])}">Open the decision card</a></p>')
    if kind == "res":
        out.append(f'<p class="mgo"><a href="#r-{esc(n["ref"])}">Open the result card</a></p>')
    return "".join(out)



def map_section(c: dict) -> str:
    if not has_map(c):
        return ""
    nodes, edges = _graph(c)
    linked = {d: [] for d in nodes}
    for a, b, why in edges:
        linked[a].append((b, why))
        # A result's own panel already leads with its takeaway; do not repeat it per link.
        linked[b].append((a, "" if nodes[b]["kind"] == "res" else why))
    order = {d: i for i, d in enumerate(nodes)}
    for links in linked.values():
        links.sort(key=lambda t: order[t[0]])

    by_kind = {k: [d for d in nodes if nodes[d]["kind"] == k] for k in KIND_NAME}
    pos = {d: i for i, d in enumerate(by_kind["dec"])}

    def dec_positions(d):
        return [pos[o] for o, _ in linked[d] if o in pos]

    reqs = barycentre_order(by_kind["req"], {d: dec_positions(d) for d in by_kind["req"]})
    cons = barycentre_order(by_kind["con"], {d: dec_positions(d) for d in by_kind["con"]})

    def stack(kind, ids, name, gloss):
        if not ids:
            return ""
        buttons = "".join(_node_button(nodes[d], [nodes[o]["code"] for o, _ in linked[d]])
                          for d in ids)
        return (f'<h3 class="mhead {kind}">{name} <span class="mpar">({gloss})</span></h3>'
                f'<div class="mstack">{buttons}</div>')

    paths = "".join(f'<path class="medge" data-from="{a}" data-to="{b}"/>' for a, b, _ in edges)
    templates = "".join(f'<template id="mp-{d}">{_panel(nodes[d], linked[d], nodes)}</template>'
                        for d in nodes)
    legend = "".join(f'<span><span class="msw {k}"></span>{label}</span>' for k, label in (
        ("req", "Requirement (why)"), ("con", "Key concept (vocabulary)"),
        ("dec", "Decision (what was chosen)"), ("res", "Result (what came out)")))
    home = ('<p class="mhint mhome">Select any box (click, tap, or Tab then Enter) to see its '
            'one-line explanation, what it connects to, and why. Esc clears.</p>')
    return (
        '<section id="map"><h2>How the pieces connect</h2>'
        f'<p class="mq"><span class="mq-k">The question</span>{inline(c["question"])}</p>'
        f'<div class="mlegend" aria-hidden="true">{legend}</div>'
        '<p class="mhint mtap">Tap a box to see what it connects to, and why.</p>'
        '<div class="mmain"><div class="mmapcol"><div class="mgrid" id="mgrid">'
        f'<svg class="medges" aria-hidden="true">{paths}</svg>'
        f'<div class="mcol mcol-left">{stack("req", reqs, "Requirements", "why")}'
        f'{stack("con", cons, "Key concepts", "vocabulary")}</div>'
        f'<div class="mcol mcol-dec">'
        f'{stack("dec", by_kind["dec"], "Decisions", "what was decided")}</div>'
        f'<div class="mcol mcol-right">'
        f'{stack("res", by_kind["res"], "Results", "what came out")}</div>'
        '</div><p class="mlanes">Left: what drove the work and the vocabulary. Middle: what '
        'was decided. Right: what came out.</p></div>'
        '<aside class="mpanel" id="mpanel" aria-live="polite">'
        '<div class="mpanel-top"><button type="button" class="mclear" disabled>'
        f'Clear selection</button></div><div class="mpanel-body">{home}</div></aside></div>'
        f'{templates}</section>')
