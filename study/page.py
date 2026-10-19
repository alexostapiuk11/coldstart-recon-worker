"""The study page: one self-contained HTML file per unit.

Sections appear in the spec's order; any section whose data is absent is skipped.
Everything is inline (CSS, SVG, a few lines of JS). The JS only switches tabs, and the
page reads fully without it.

Chart colours --c0..--c7 are the dataviz skill's validated categorical palette (light and
dark steps, fixed order). --t0..--t7 are the ink for a value printed inside a segment of
that colour: black or white, whichever clears 4.5:1 on the fill.
"""

from __future__ import annotations

from study.links import link_index, req_label, traced
from study.map import MAP_CSS, MAP_JS, has_map, map_section
from study.schema import flow_phases, phased, so_ids
from study.seq import list_below, sequence_html
from study.svg import chart_html, diagram_html, segment_slots
from study.text import esc, inline, plural, resolve_links, unit_url

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
.cgrid{grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr))}
.rgrid{grid-template-columns:repeat(auto-fill,minmax(min(100%,max(300px,calc((100% - 24px)/3))),1fr))}
.dlegend{color:var(--muted);font-size:14px;margin:6px 0 0}
details.src{background:transparent}details.src summary{font-size:17px}
details.src ul{margin:8px 0 4px;padding-left:20px}
.crow{margin:10px 0 0}.crow b{display:block;color:var(--muted);font-weight:600;font-size:13px;
text-transform:uppercase;letter-spacing:.05em;margin-bottom:1px}
.why{color:var(--muted);font-size:14px}
.row{display:grid;grid-template-columns:104px 1fr;gap:10px;margin:6px 0;align-items:baseline}
.row b{color:var(--muted);font-weight:600;font-size:13px;text-transform:uppercase;letter-spacing:.04em}
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
.diagram-text{display:none;font-size:15px}.diagram-text small{color:var(--muted);font-size:13px}
.diagram-text .kmark{color:var(--accent);font-weight:600;text-transform:uppercase;letter-spacing:.04em;font-size:11px}
.kmark{white-space:nowrap}
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
.seg.dim{fill:var(--line);stroke:var(--muted);stroke-width:.75}.segtext.dim{fill:var(--muted)}
.chip.dim{background:var(--line);box-shadow:inset 0 0 0 1px var(--muted)}
.deltas{margin:8px 0 4px;font-size:.9em}.deltas .dhead{color:var(--muted);font-weight:600;
font-size:13px;text-transform:uppercase;letter-spacing:.04em}
.deltas ul{margin:4px 0;padding-left:18px}.deltas li{margin:2px 0}.deltas b{margin-right:4px}
.zero{stroke:var(--fg);stroke-width:1.5;stroke-dasharray:4 3}.axis{stroke:var(--line);stroke-width:1.5}
.whisker{stroke:var(--c0);stroke-width:2.5;stroke-linecap:round}.est{fill:var(--c0);stroke:var(--card);stroke-width:2}
.shade{fill:var(--line);opacity:.45}.inum{font-size:12px;fill:var(--muted)}
.axlabel{font-size:12px;fill:var(--muted)}.iest{font-weight:600}
.ilabel,.inum,.iest,.axlabel{paint-order:stroke;stroke:var(--card);stroke-width:4px;stroke-linejoin:round}
.ghost{fill:none;stroke:var(--fg);stroke-width:1.5;stroke-dasharray:5 3}
.gcap{font-size:12px;fill:var(--fg);font-style:italic;paint-order:stroke;stroke:var(--card);
stroke-width:4px;stroke-linejoin:round}
.prange{stroke:var(--muted);stroke-width:2.5;stroke-linecap:round}
.pgap{stroke:var(--muted);stroke-width:1.5;stroke-dasharray:3 4}
.pgrid{stroke:var(--line);stroke-width:1}.paxis{stroke:var(--muted);stroke-width:1.2}
.pdot{stroke:var(--card);stroke-width:1.5}
.pk0{fill:var(--c0)}.pk1{fill:var(--c1)}.pk2{fill:var(--c6)}.pk3{fill:var(--c3)}
.pmax{fill:var(--card);stroke:var(--fg);stroke-width:2}
.pnum{font-size:12px;fill:var(--fg)}.pmaxt{fill:var(--muted);font-style:italic}
.pnum,.ptick{paint-order:stroke;stroke:var(--card);stroke-width:4px;stroke-linejoin:round}
.cnote{color:var(--muted);font-size:14px;margin:4px 0 6px}
.xk0{color:var(--c0)}.xk1{color:var(--c1)}.xk2{color:var(--c6)}.xk3{color:var(--c2)}
.xk4{color:var(--c3)}.xk5{color:var(--c4)}
.xyl{fill:none;stroke:currentColor;stroke-width:2;stroke-linejoin:round}.xyl.r{stroke-dasharray:6 4}
.xym{fill:currentColor;stroke:var(--card);stroke-width:1.5}
.xym.r{fill:var(--card);stroke:currentColor;stroke-width:2}
.xyw{stroke:currentColor;stroke-width:1.5}
.xygrid{stroke:var(--line);stroke-width:1}.xyaxis,.xytick{stroke:var(--muted);stroke-width:1.2}
.xyref{stroke:var(--fg);stroke-width:1.2;stroke-dasharray:4 4;opacity:.8}
.xyband{fill:var(--line);opacity:.6}
.xyv{font-size:12px;font-weight:600;fill:var(--fg)}
.xyrt,.xybt{font-size:12px;fill:var(--muted);font-style:italic}
.xylead{stroke:var(--muted);stroke-width:1}
.xyf{fill:none;stroke:var(--fg);stroke-width:2;stroke-linejoin:round}
.xyn{font-size:12px;font-weight:700;fill:var(--fg)}.xypl{font-size:12px;fill:var(--fg)}
.xyfl{font-size:12px;fill:var(--fg);font-style:italic}
.xyv,.xyrt,.xybt,.xyt,.xyax,.xyn,.xypl,.xyfl{paint-order:stroke;stroke:var(--card);stroke-width:4px;stroke-linejoin:round}
.xychip{vertical-align:-2px;margin-right:6px;overflow:visible}
.xyleg{font-size:14px}.xyleg small{font-size:inherit;color:var(--muted)}
.shswatch{display:inline-block;width:14px;height:10px;margin-right:6px;background:var(--line);
opacity:.7;border-radius:2px;vertical-align:0}
.legend{list-style:none;padding:0;margin:6px 0;display:flex;gap:14px;flex-wrap:wrap;font-size:13px}
.chip{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
.flow{display:flex;gap:8px;flex-wrap:wrap;counter-reset:s}
.step{flex:1 1 160px;background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:10px 12px;position:relative}.step:before{counter-increment:s;content:counter(s);
position:absolute;top:-10px;left:10px;background:var(--accent);color:var(--bg);width:20px;
height:20px;border-radius:50%;font-size:12px;text-align:center;line-height:20px}
.fl-sum{margin:0 0 10px}
.fl-strip{list-style:none;padding:0;margin:0 0 18px;display:flex;flex-wrap:wrap;gap:8px}
.fl-strip a{display:flex;flex-direction:column;gap:1px;padding:6px 12px 6px 30px;position:relative;
border:1.5px solid var(--accent);border-radius:8px;background:var(--card);color:var(--fg);
text-decoration:none;font-size:14px;line-height:1.35;max-width:100%}
.fl-strip a:hover{background:var(--soft)}
.fl-strip a:before{content:"";position:absolute;left:11px;top:50%;width:9px;height:9px;
margin-top:-5px;background:var(--accent);transform:rotate(45deg)}
.fl-sdate{color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
.fl-slabel{font-weight:600}
.fl-tl{position:relative}
.fl-tl:before{content:"";position:absolute;left:16.5px;top:12px;bottom:0;width:3px;opacity:.55;
background:var(--muted)}
.fl-phase:last-child .fl-step:last-child:after{content:"";position:absolute;left:12px;top:48px;
bottom:0;width:12px;background:var(--bg)}
.fl-phase{position:relative}
.fl-band{position:relative;display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 12px;
margin:6px 0 10px 48px;padding:6px 0 4px;border-bottom:2px solid var(--fg)}
.fl-band:before{content:"";position:absolute;left:-37px;top:12px;width:14px;height:14px;
background:var(--fg);border:3px solid var(--bg);box-sizing:content-box;margin:-3px}
.fl-band h3{margin:0;font-size:18px}
.fl-pn{color:var(--muted);font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.06em}
.fl-pc{color:var(--muted);font-size:13px;margin-left:auto}
.fl-steps{list-style:none;margin:0;padding:0}
.fl-step{position:relative;padding:0 0 12px 48px;scroll-margin-top:64px}
.fl-node{position:absolute;left:4px;top:12px;width:28px;height:28px;border-radius:50%;
background:var(--card);border:2px solid var(--muted);color:var(--fg);font-size:13px;font-weight:700;
display:flex;align-items:center;justify-content:center;font-variant-numeric:tabular-nums}
.fl-card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
.fl-card h4{margin:0 0 4px;font-size:16px;line-height:1.35}
.fl-detail{color:var(--muted);font-size:15px}
.fl-side{margin-top:8px;font-size:14px}
.fl-side>*+*{margin-top:6px}
.fl-out b,.fl-ev b{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;
letter-spacing:.05em;margin-right:4px}
.fl-when{display:inline-block;color:var(--muted);font-size:12px;border:1px solid var(--line);
border-radius:99px;padding:0 8px;font-variant-numeric:tabular-nums;white-space:nowrap}
.fl-dec{display:inline-block;font-size:13px;border:1px solid var(--accent);border-radius:99px;
padding:1px 10px;text-decoration:none;background:var(--card)}
.fl-dec:hover{background:var(--soft)}.fl-dec b{font-weight:700}
.fl-ev{color:var(--muted);font-size:12.5px;overflow-wrap:anywhere}
.fl-ev code{background:transparent;padding:0;font-size:12px}
.fl-tag{display:inline-block;background:var(--accent);color:var(--bg);font-size:11px;font-weight:700;
letter-spacing:.08em;text-transform:uppercase;border-radius:4px;padding:1px 7px;margin-bottom:4px}
.fl-ms .fl-node{left:0;top:8px;width:36px;height:36px;background:var(--accent);
border-color:var(--accent);color:var(--bg);font-size:15px;box-shadow:0 0 0 4px var(--soft)}
.fl-ms .fl-card{border:2px solid var(--accent);border-left-width:6px;background:var(--soft)}
.fl-ms .fl-card h4{font-size:17px}
.callout{border-left:4px solid var(--accent);padding:6px 12px;background:var(--soft);
border-radius:0 8px 8px 0;margin:8px 0}
.limits{border-left-color:var(--warn);background:var(--warnsoft)}
details.more{background:transparent;border-style:dashed;margin-top:10px}
details{background:var(--card);border:1px solid var(--line);border-radius:8px;
padding:8px 12px;margin:6px 0}summary{cursor:pointer;font-weight:600}
code{font-size:.92em;background:var(--soft);padding:1px 5px;border-radius:4px}
.src{font-size:13px;color:var(--muted)}
.hero .lead,.answer{max-width:1100px}
.readfirst{display:inline-block;font-size:15px;background:var(--card);border:1px solid var(--line);
border-left:4px solid var(--warn);border-radius:0 8px 8px 0;padding:5px 12px;margin:0 0 8px}
.readfirst b{color:var(--muted);font-weight:600;margin-right:4px}
.answer{border-left:4px solid var(--accent);background:var(--soft);border-radius:0 10px 10px 0;
padding:10px 14px;margin:10px 0 4px}.answer p{margin:4px 0 8px}
.akicker{color:var(--muted);font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.06em}
.achips{display:flex;flex-wrap:wrap;gap:6px}
.achip{padding:3px 10px;border:1px solid var(--accent);border-radius:99px;background:var(--card);
font-size:14px;text-decoration:none;color:var(--fg)}
.achip:hover{background:var(--soft)}
.code{display:inline-block;font-size:12px;font-weight:700;line-height:1.5;color:var(--accent);
border:1px solid var(--accent);border-radius:5px;padding:0 5px;margin-right:8px;vertical-align:2px;
font-variant-numeric:tabular-nums}
.links{font-size:14px;color:var(--muted);margin:8px 0 0;line-height:1.5}
.links b{font-weight:600;color:var(--muted);margin-right:2px}
.links a{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:2px}
.links .lc{font-weight:700;font-variant-numeric:tabular-nums}.links .none{font-style:italic}
.callout.links{font-size:15px;color:var(--fg);margin-top:10px}
@media (min-width:1100px){body{font-size:18px}h1{font-size:36px}h2{font-size:26px}h3{font-size:18px}
.lead{font-size:21px}.why{font-size:16px}
.fl-card{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:4px 32px;padding:12px 18px}
.fl-side{margin-top:0;padding-left:20px;border-left:1px solid var(--line)}
.fl-card h4{font-size:18px}.fl-ms .fl-card h4{font-size:19px}.fl-detail{font-size:16px}
.fl-side{font-size:15px}.fl-band h3{font-size:20px}}
@media (max-width:600px){.diagram{display:none}.diagram-text{display:block}.dlegend{display:none}
h1{font-size:24px}.lead{font-size:16px}
.row{display:block}.row b{display:block;margin-bottom:1px}
nav.pills{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none;-webkit-overflow-scrolling:touch;
--fadeL:#000;--fadeR:transparent;
-webkit-mask-image:linear-gradient(#000,#000),linear-gradient(to right,var(--fadeL),#000 36px,#000 calc(100% - 36px),var(--fadeR));
mask-image:linear-gradient(#000,#000),linear-gradient(to right,var(--fadeL),#000 36px,#000 calc(100% - 36px),var(--fadeR));
-webkit-mask-size:100% 1px,100% 100%;mask-size:100% 1px,100% 100%;
-webkit-mask-position:0 100%,0 0;mask-position:0 100%,0 0;-webkit-mask-repeat:no-repeat;mask-repeat:no-repeat}
nav.pills[data-more=""]{-webkit-mask-image:none;mask-image:none}
nav.pills[data-more~="left"]{--fadeL:transparent}nav.pills[data-more="left"]{--fadeR:#000}
nav.pills::after{content:"";flex:none;width:32px}
nav.pills::-webkit-scrollbar{display:none}nav.pills a{flex:none}
.blabel,.btotal,.inum,.pnum,.gcap,.segtext,.axlabel{font-size:15px}
.xyt,.xyax,.xyv,.xyrt,.xybt,.xyn,.xypl,.xyfl{font-size:15px}}
"""

JS = """
for (const n of document.querySelectorAll('nav.pills')) {
  // Which edges hide pills: the phone CSS fades those edges, and none once all fit.
  const mark = () => { const more = [];
    if (n.scrollLeft > 2) more.push('left');
    if (n.scrollLeft + n.clientWidth < n.scrollWidth - 2) more.push('right');
    n.dataset.more = more.join(' '); };
  n.addEventListener('scroll', mark, {passive: true});
  addEventListener('resize', mark);
  mark();
}
for (const g of document.querySelectorAll('[data-tabs]')) {
  const tabs = g.querySelectorAll('[role=tab]'), panels = g.querySelectorAll('[role=tabpanel]');
  const show = i => { tabs.forEach((t, j) => t.setAttribute('aria-selected', j === i));
    panels.forEach((p, j) => { p.hidden = j !== i; }); };
  tabs.forEach((t, i) => t.addEventListener('click', () => show(i)));
  show(0);
}
"""

# Sequence views (study.seq); shipped only on a page that has one.
SEQ_CSS = """
.sq{container-type:inline-size}.sqd{width:100%;height:auto;display:block}
.sq-text{display:none;font-size:15px}.sq-text small{color:var(--muted);font-size:13px}
.sq-text ul{margin:4px 0 8px;padding-left:20px}.sq-steps{margin:0;padding-left:28px}
.sq-steps li{margin:4px 0}.sq-gapi{list-style:none;color:var(--muted);margin-left:-8px}
.sqw{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;
color:var(--muted)}.sqw-bad{color:var(--warn)}
.sqbox{fill:var(--card);stroke:var(--accent);stroke-width:1.5}
.k-person .sqbox{fill:var(--soft)}.k-external .sqbox{stroke:var(--muted);stroke-dasharray:4 3}
.k-store .sqbox{fill:var(--warnsoft);stroke:var(--warn)}.k-focus .sqbox{fill:var(--soft);stroke-width:2.5}
.sqh{font-size:14px;font-weight:600;fill:var(--fg)}.sqsub{font-size:12px;fill:var(--muted)}
.sqlife{stroke:var(--muted);stroke-width:1.2;stroke-dasharray:5 5}
.sqdown{stroke:var(--warn);stroke-width:2;stroke-dasharray:1.5 4;stroke-linecap:round}
.sqa{fill:none;stroke:var(--fg);stroke-width:1.6}
.sqreply{stroke:var(--muted);stroke-dasharray:6 4}
.sqfault{stroke:var(--warn);stroke-width:2.2}
.sqdup{stroke:var(--c7);stroke-width:2.6}
.sqns{stroke-dasharray:6 4}.sqnsx{stroke:var(--warn);stroke-width:2.5;stroke-linecap:round}
.sqah-solid{fill:var(--fg)}.sqah-open{fill:none;stroke:var(--muted);stroke-width:1.5}
.sqah-fault{fill:var(--warn)}.sqah-dup{fill:var(--c7)}.sqbolt{fill:var(--warn)}
.sqx{stroke:var(--warn);stroke-width:3.5;stroke-linecap:round}
.sqnote{fill:var(--soft);stroke:var(--line)}.sqbreak{stroke:var(--muted);stroke-width:1.5}
.sqnum{fill:var(--card);stroke:var(--muted);stroke-width:1.2}
.sqn{font-size:12px;font-weight:700;fill:var(--fg)}
.sqlabel{font-size:13px;fill:var(--fg)}.sqtext{font-size:12px;fill:var(--muted);font-style:italic}
.sqcrash{font-size:13px;font-weight:700;fill:var(--warn)}
.sqgap{font-size:13px;font-weight:600;font-style:italic;fill:var(--muted)}
.sqbadge{fill:color-mix(in srgb,var(--warn) 16%,var(--card));stroke:var(--warn)}
.sqbadge-dup{fill:color-mix(in srgb,var(--c7) 16%,var(--card));stroke:var(--c7)}
.sqbt{font-size:12px;font-weight:700;fill:var(--fg)}
.sqlabel,.sqtext,.sqcrash,.sqgap{paint-order:stroke;stroke:var(--card);stroke-width:4px;
stroke-linejoin:round}.sqnotet{stroke:none}
"""


# Matrix charts (study.matrix); shipped only on a page that has one. A tone mixes a theme
# token into the card colour; a status is a texture: hatched (predicted), solid
# (observed), a dotted outline (pending).
MATRIX_CSS = """
.mxwrap{overflow-x:auto;margin:4px 0}
.mx{border-collapse:separate;border-spacing:3px;width:100%;font-size:14px;line-height:1.35}
.mx th{font-weight:600;text-align:left;vertical-align:bottom;padding:4px 6px;color:var(--fg)}
.mx th small,.mx td small{display:block;font-weight:400;color:var(--muted);font-size:12px}
.mx tbody th{vertical-align:middle;white-space:nowrap}
.mxunit{color:var(--muted);font-weight:400;font-size:12px}
.mx td{padding:6px 8px;border-radius:5px;border:1px solid var(--line);vertical-align:middle;
background-color:var(--card)}
.mx .t-bad{background-color:color-mix(in srgb,var(--c7) 17%,var(--card))}
.mx .t-warn{background-color:color-mix(in srgb,var(--c3) 22%,var(--card))}
.mx .t-ok{background-color:color-mix(in srgb,var(--c2) 18%,var(--card))}
.mx .st-observed{border-color:var(--muted)}
.mx .st-predicted{background-image:repeating-linear-gradient(135deg,transparent 0 5px,
color-mix(in srgb,var(--fg) 16%,transparent) 5px 6.5px)}
.mx .st-pending{border:2px dotted var(--muted)}
.mx .st-none,.mx .st-na{background-color:transparent;color:var(--muted)}
.mx .st-na{font-style:italic}
.mxg{font-weight:700;margin-right:4px}
.mxs{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.mxleg{font-size:13px}
.mxsw{display:inline-block;width:20px;height:14px;border-radius:3px;margin-right:6px;
vertical-align:-2px;border:1px solid var(--muted);background-color:var(--soft)}
.mxsw.st-none,.mxsw.st-na{background-color:transparent;border-color:var(--line)}
.mxsw.st-pending{border:2px dotted var(--muted)}
.mxsw.st-predicted{background-image:repeating-linear-gradient(135deg,transparent 0 4px,
color-mix(in srgb,var(--fg) 30%,transparent) 4px 5.5px)}
.mxswt{width:auto;height:auto;border:0;background:none;font-weight:700;margin-right:4px}
@media (max-width:600px){.mx,.mx tbody,.mx tr,.mx th,.mx td{display:block;width:auto}
.mx{border-spacing:0;font-size:15px}
.mx thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.mx tr{border:1px solid var(--line);border-radius:8px;padding:6px;margin:0 0 8px}
.mx tbody th{white-space:normal;padding:2px 2px 6px}
.mx td{margin:4px 0}
.mx td::before{content:attr(data-col) ": ";font-weight:600;color:var(--fg)}
.mx td .mxs{position:static;width:auto;height:auto;clip:auto;display:block;color:var(--muted);
font-size:13px;white-space:normal}}
"""


def seq_css(diagrams: list[tuple[str, float]]) -> str:
    """SEQ_CSS, then for each (uid, width) a container query that swaps the diagram for
    its text list below that width (study.seq.list_below)."""
    rules = "".join(f"@container (max-width:{w:.0f}px){{#sq-{uid} .sqd{{display:none}}"
                    f"#sq-{uid} .sqleg{{display:none}}#sq-{uid} .sq-text{{display:block}}}}\n"
                    for uid, w in diagrams)
    return SEQ_CSS + rules


def _sequences(c):
    """(uid, list width) for each sequence view on the page."""
    return [(f"{c['id']}-{i}", list_below(v)) for i, v in enumerate(c.get("views", []))
            if v.get("style") == "sequence"]


LEVEL_NAMES = {"context": "1 Context", "container": "2 Containers",
               "component": "3 Components", "dynamic": "4 One run"}


def _link(anchor, code, label):
    return f'<a href="#{esc(anchor)}"><span class="lc">{esc(code)}</span> {esc(label)}</a>'


def _links_row(label, links, none="", cls="links"):
    """One compact line: a label, then links separated by dots (or why there are none)."""
    if links:
        body = " · ".join(links)
    elif none:
        body = f'<span class="none">{inline(none)}</span>'
    else:
        return ""
    return f'<div class="{cls}"><b>{label}</b> {body}</div>'


def _dec_links(ix, decisions):
    return [_link(f"d-{d['id']}", ix["dec_code"][d["id"]], d["title"]) for d in decisions]


def _concepts(c):
    ix = link_index(c) if traced(c) else None
    cards = []
    for t in c["concepts"]:
        extra = ""
        if t.get("analogy"):
            extra += f'<div class="crow"><b>Like</b><div>{inline(t["analogy"])}</div></div>'
        if t.get("why"):
            extra += f'<div class="crow"><b>Matters</b><div>{inline(t["why"])}</div></div>'
        # c- for concepts, d- for decisions, r- for results: the prefixes keep ids unique.
        anchor = f' id="c-{esc(t["id"])}"' if t.get("id") else ""
        code = ""
        if ix and t.get("id"):
            code = f'<span class="code">{ix["con_code"][t["id"]]}</span>'
            extra += _links_row("Used by:", _dec_links(ix, ix["used_by"][t["id"]]))
        cards.append(f'<div class="card"{anchor}><h3>{code}{esc(t["term"])}</h3>'
                     f'<div>{inline(t["plain"])}</div>{extra}</div>')
    title = "Need to know first" if c["kind"] == "artifact" else "The ideas"
    return (f'<section id="concepts"><h2>{title}</h2>'
            f'<div class="grid cgrid">{"".join(cards)}</div></section>')


def _requirements(c):
    if not traced(c):
        reqs = "".join(f'<div class="card"><b>{inline(r["text"])}</b>'
                       f'<div class="why">{inline(r["why"])}</div></div>'
                       for r in c["requirements"])
        return (f'<section id="why"><h2>Requirements that drove everything</h2>'
                f'<div class="grid rgrid">{reqs}</div></section>')
    ix = link_index(c)
    cards = []
    for r in c["requirements"]:
        # The heading is the requirement's short name, the words the map shows; the full
        # text follows when it says more.
        text = f'<div>{inline(r["text"])}</div>' if req_label(r) != r["text"] else ""
        none = f"no decision. {r['unlinked_reason']}" if r.get("unlinked_reason") else ""
        answered = _links_row("Answered by:", _dec_links(ix, ix["answered_by"][r["id"]]), none)
        cards.append(f'<div class="card" id="req-{esc(r["id"])}"><h3><span class="code">'
                     f'{esc(r["id"])}</span>{esc(req_label(r))}</h3>{text}'
                     f'<div class="why">{inline(r["why"])}</div>{answered}</div>')
    return (f'<section id="why"><h2>Requirements that drove everything</h2>'
            f'<div class="grid rgrid">{"".join(cards)}</div></section>')


DIAGRAM_LEGEND = ("solid box: part of this system · dashed: outside it · bold: where this "
                  "study's key step happens")


def _views(c):
    legend = (f'<p class="dlegend">{esc(DIAGRAM_LEGEND)}</p>' if c["kind"] == "artifact"
              else "")
    tabs, panels = [], []
    for i, v in enumerate(c["views"]):
        name = LEVEL_NAMES.get(v["level"], v["title"])
        tabs.append(f'<button role="tab" aria-selected="false">{esc(name)}</button>')
        uid = f"{c['id']}-{i}"
        drawn = (sequence_html(v, uid) if v.get("style") == "sequence"
                 else diagram_html(v, uid) + legend)
        panels.append(f'<div role="tabpanel"><h3>{esc(v["title"])}</h3>'
                      f'<p class="why">{inline(v["caption"])}</p>{drawn}</div>')
    head = "System views" + (" (C4)" if c["kind"] == "artifact" else "")
    return (f'<section id="views"><h2>{head}</h2><div class="card" data-tabs>'
            f'<div class="tabs" role="tablist">{"".join(tabs)}</div>{"".join(panels)}</div>'
            "</section>")


def _decision_links(c, ix, d):
    """The decision's code badge and its 'Serves:' and 'Seen in:' rows (traced units)."""
    if not ix:
        return "", ""
    serves = [_link(f"req-{s['req']}", s["req"], req_label(ix["req"][s["req"]]))
              for s in d.get("serves", [])]
    seen = [_link(f"r-{i}", ix["res_code"][i], c["results"][i]["title"])
            for i in ix["seen_in"][d["id"]]]
    return (f'<span class="code">{ix["dec_code"][d["id"]]}</span>',
            _links_row("Serves:", serves) + _links_row("Seen in:", seen))


def _decisions(c):
    ix = link_index(c) if traced(c) else None
    cards = []
    for d in c["decisions"]:
        opts = "".join(
            f'<span class="opt{" chosen" if o == d["chosen"] else ""}">{inline(o)}</span>'
            for o in d["options"])
        code, rows = _decision_links(c, ix, d)
        cards.append(
            f'<div class="card" id="d-{esc(d["id"])}"><h3>{code}{esc(d["title"])}</h3>{rows}'
            f'<div class="row"><b>Problem</b><div>{inline(d["problem"])}</div></div>'
            f'<div class="row"><b>Options</b><div>{opts}</div></div>'
            f'<div class="row"><b>Because</b><div>{inline(d["why_short"])}</div></div>'
            f'<div class="row cost"><b>Cost</b><div>{inline(d["cost_short"])}</div></div>'
            '<details class="more"><summary>Full reasoning and cost</summary>'
            f'<div class="row"><b>Because</b><div>{inline(d["why"])}</div></div>'
            f'<div class="row cost"><b>Cost</b><div>{inline(d["cost"])}</div></div></details></div>')
    return (f'<section id="decisions"><h2>Core decisions</h2>'
            f'<div class="grid2">{"".join(cards)}</div></section>')


def _results(c):
    titles = {d["id"]: d["title"] for d in c.get("decisions", [])}
    # One colour per segment name across the page's stacked charts.
    slots = segment_slots([r["chart"] for r in c["results"]
                           if r["chart"]["type"] == "stacked_bars"])
    ix = link_index(c) if traced(c) else None
    decs = {d["id"]: d for d in c.get("decisions", [])}
    cards = []
    for i, r in enumerate(c["results"]):
        so, code = "", ""
        if ix:
            code = f'<span class="code">{ix["res_code"][i]}</span>'
            none = f"no decision. {r['so_none_reason']}" if r.get("so_none_reason") else ""
            so = _links_row("Rests on:", _dec_links(ix, [decs[d] for d in so_ids(r)]), none,
                            cls="callout links")
        elif so_ids(r):
            links = ", ".join(f'<a href="#d-{esc(d)}">{esc(titles[d])}</a>' for d in so_ids(r))
            so = f'<div class="callout">So: {links}</div>'
        computed = (f'<div class="row"><b>How it is computed</b><div>{inline(r["arithmetic"])}'
                    '</div></div>' if r.get("arithmetic") else "")
        cards.append(
            f'<div class="card" id="r-{i}"><h3>{code}{esc(r["title"])}</h3>'
            f'{chart_html(r["chart"], f"r{i}", slots)}'
            f'<div class="row"><b>Axis</b><div>{inline(r["axis"])}</div></div>'
            f'<div class="row"><b>Read it as</b><div>{inline(r["read_as"])}</div></div>'
            f'{computed}{so}</div>')
    head = "Results, as meaning" if c["kind"] == "artifact" else "In pictures"
    return (f'<section id="results"><h2>{head}</h2>'
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


def _plain_flow(c):
    steps = "".join(f'<div class="step"><b>{inline(s["label"])}</b>'
                    f'<div class="why">{inline(s["detail"])}</div></div>' for s in c["flow"])
    return (f'<section id="flow"><h2>Implementation flow</h2>'
            f'<div class="flow">{steps}</div></section>')


def _evidence(ev):
    """Commits as plain monospace text: sha, then the repo when it is not this one, then
    the note."""
    parts = []
    for e in ev:
        tail = [f"in {esc(e['repo'])}"] if e.get("repo") else []
        tail += [esc(e["note"])] if e.get("note") else []
        parts.append(f"<code>{esc(e['commit'])}</code>" + (" " + ", ".join(tail) if tail else ""))
    return f'<div class="fl-ev"><b>Evidence</b> {" · ".join(parts)}</div>'


def _flow_step(n, s, codes, titles):
    ms = bool(s.get("milestone"))
    tag = '<span class="fl-tag">Milestone</span>' if ms else ""
    side = []
    if s.get("when"):
        side.append(f'<span class="fl-when">{esc(s["when"])}</span>')
    if s.get("output"):
        side.append(f'<div class="fl-out"><b>Output:</b> {inline(s["output"])}</div>')
    if s.get("decision"):
        d = s["decision"]
        side.append(f'<div><a class="fl-dec" href="#d-{esc(d)}"><b>Decision {codes[d]}</b> '
                    f'{esc(titles[d])}</a></div>')
    if s.get("evidence"):
        side.append(_evidence(s["evidence"]))
    return (f'<li class="fl-step{" fl-ms" if ms else ""}" id="flow-s{n}">'
            f'<span class="fl-node" aria-hidden="true">{n}</span><div class="fl-card">'
            f'<div class="fl-main">{tag}<h4>{inline(s["label"])}</h4>'
            f'<div class="fl-detail">{inline(s["detail"])}</div></div>'
            f'<div class="fl-side">{"".join(side)}</div></div></li>')


def _flow(c):
    """The flow as a vertical timeline: a milestone strip, then each phase as a band over
    its steps. A unit whose flow has no phase or milestone keeps the plain cards."""
    if not phased(c):
        return _plain_flow(c)
    flow = c["flow"]
    codes = link_index(c)["dec_code"]
    titles = {d["id"]: d["title"] for d in c.get("decisions", [])}
    phases = flow_phases(flow)
    marks = [(n, s) for n, s in enumerate(flow, 1) if s.get("milestone")]
    strip = "".join(f'<li><a href="#flow-s{n}"><span class="fl-sdate">{esc(s["when"])}</span>'
                    f'<span class="fl-slabel">{esc(s["label"])}</span></a></li>'
                    for n, s in marks)
    body = []
    for i, (name, steps) in enumerate(phases, 1):
        head = (f'<div class="fl-band"><span class="fl-pn">Phase {i} of {len(phases)}</span>'
                f'<h3>{esc(name)}</h3><span class="fl-pc">{plural(len(steps), "step")}'
                "</span></div>")
        items = "".join(_flow_step(n, s, codes, titles) for n, s in steps)
        body.append(f'<div class="fl-phase">{head}<ol class="fl-steps" start="{steps[0][0]}">'
                    f"{items}</ol></div>")
    summary = (f'{plural(len(flow), "step")} in {plural(len(phases), "phase")}, '
               f'{plural(len(marks), "milestone")}')
    return (f'<section id="flow"><h2>Implementation flow</h2>'
            f'<p class="why fl-sum">{summary}. Milestones are the points where something '
            'durable existed; jump to one:</p>'
            f'<ol class="fl-strip" aria-label="Milestones">{strip}</ol>'
            f'<div class="fl-tl">{"".join(body)}</div></section>')


def _answer_first(c):
    """The 30-second answer and one chip per result, so the page opens on the conclusion."""
    pitch = c.get("interview", {}).get("pitch30")
    if not pitch or not c.get("results"):
        return ""
    chips = "".join(f'<a class="achip" href="#r-{i}">{esc(r.get("short") or r["title"])}</a>'
                    for i, r in enumerate(c["results"]))
    return (f'<div class="answer"><div class="akicker">Answer first</div>'
            f'<p>{inline(pitch)}</p><div class="achips">{chips}</div></div>')


def _read_first(c):
    """A banner under the title linking each prerequisite page (new tab)."""
    if not c.get("prereqs"):
        return ""
    links = " · ".join(f'<a href="{esc(unit_url(c, p["unit"]))}" target="_blank" '
                       f'rel="noopener">{esc(p["label"])}</a>' for p in c["prereqs"])
    return f'<div class="readfirst"><b>Read first:</b> {links}</div>'


def render_page(c: dict) -> str:
    c = resolve_links(c, "page")
    art = c["kind"] == "artifact"
    sections, nav = [], []

    def add(sid, label, html):
        sections.append(html)
        nav.append(f'<a href="#{sid}">{label}</a>')

    if c.get("concepts"):
        add("concepts", "Concepts", _concepts(c))
    if art:
        add("why", "Requirements", _requirements(c))
    if c.get("views"):
        add("views", "Views", _views(c))
    if c.get("decisions"):
        add("decisions", "Decisions", _decisions(c))
    if c.get("flow"):
        add("flow", "Flow", _flow(c))
    if c.get("results"):
        add("results", "Results", _results(c))
    if has_map(c):
        add("map", "Map", map_section(c))
    if c.get("interview"):
        add("interview", "Interview", _interview(c))
    rec = "".join(f"<details><summary>{inline(r['q'])}</summary><p>{inline(r['a'])}</p></details>"
                  for r in c["recall"])
    add("recall", "Recall", f'<section id="recall"><h2>Recall check</h2>'
        f'<p class="why">Answer out loud first, then open.</p>{rec}</section>')
    src = "".join(f"<li><code>{esc(s['file'])}</code>: {esc(s['section'])}</li>"
                  for s in c["sources"])
    n = len(c["sources"])
    count = "1 file and section" if n == 1 else f"{n} files and sections"
    add("sources", "Sources", f'<section id="sources"><details class="src"><summary>Sources, '
        f'{count}</summary><ul>{src}</ul></details></section>')

    css, js = (CSS + MAP_CSS, JS + MAP_JS) if has_map(c) else (CSS, JS)
    if _sequences(c):
        css += seq_css(_sequences(c))
    if any(r["chart"]["type"] == "matrix" for r in c.get("results", [])):
        css += MATRIX_CSS
    if art:
        lead = f'<p class="lead">{inline(c["question"])}</p>{_answer_first(c)}'
    else:
        lead = f'<p class="why">Used by: {esc(", ".join(c["used_by"]))}</p>'
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{esc(c["short_title"])}</title><style>{css}</style></head><body><main>'
        f'<header class="hero"><div class="kicker">Study page · about {c["minutes"]} min</div>'
        f'<h1>{esc(c["title"])}</h1>{_read_first(c)}{lead}</header>'
        f'<nav class="pills">{"".join(nav)}</nav>{"".join(sections)}</main>'
        f'<script>{js}</script></body></html>')
