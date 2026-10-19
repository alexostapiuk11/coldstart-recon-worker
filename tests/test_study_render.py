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
    # The column gap widens to fit edge labels, so read the box positions from the SVG.
    out = diagram_html(artifact_unit()["views"][0], "u")
    line = re.search(r'<line class="edge" x1="([\d.]+)" y1="[\d.]+" x2="([\d.]+)"', out)
    x1, x2 = float(line.group(1)), float(line.group(2))
    rects = [float(x) for x in re.findall(r'<rect x="([\d.]+)"', out)]
    assert rects[0] + 170 <= x1 < x2 <= rects[1]


def test_diagram_column_gap_fits_the_widest_same_row_edge_label():
    # "submits 3 jobs" is wider than the default 50 px gap; the label must sit between boxes.
    out = diagram_html(artifact_unit()["views"][0], "u")
    rects = [float(x) for x in re.findall(r'<rect x="([\d.]+)"', out)]
    gap = rects[2] - (rects[1] + 170)
    assert gap >= len("submits 3 jobs") * 6.2 + 8


def test_stacked_chart_scales_segments_and_lists_a_legend():
    chart = artifact_unit()["results"][0]["chart"]
    out = chart_html(chart, "r0")
    assert out.count("<rect") >= 4  # four segments
    assert "load" in out and "compile" in out  # legend
    assert "59.5" not in out  # a sum of per-phase medians is not shown unless asked
    widths = [float(w) for w in re.findall(r'class="seg s\d" [^>]*width="([\d.]+)"', out)]
    assert widths[0] > widths[1] > widths[3]  # 40.5 > 19.0 > 0.3, proportional


def test_stacked_chart_prints_totals_only_when_asked():
    chart = dict(artifact_unit()["results"][0]["chart"], show_totals=True)
    out = chart_html(chart, "r0")
    assert "59.5 s" in out and "21.6 s" in out
    view_w = int(re.search(r'viewBox="0 0 (\d+)', out).group(1))
    bare = chart_html(artifact_unit()["results"][0]["chart"], "r0")
    assert view_w > int(re.search(r'viewBox="0 0 (\d+)', bare).group(1))


def test_chart_numbers_show_up_to_two_decimals_without_trailing_zeros():
    chart = {"type": "bars", "unit": "s",
             "items": [{"label": "a", "value": 19.01}, {"label": "b", "value": 15.68},
                       {"label": "c", "value": 4.00}, {"label": "d", "value": 35792}]}
    out = chart_html(chart, "r2")
    for shown in (">19.01 s<", ">15.68 s<", ">4 s<", ">35,792 s<"):
        assert shown in out


def test_stacked_segment_label_prints_only_when_it_fits():
    chart = {"type": "stacked_bars", "unit": "s", "bars": [{"label": "A", "segments": [
        {"name": "big", "value": 45.83}, {"name": "tiny", "value": 0.09}]}]}
    out = chart_html(chart, "r3")
    assert ">45.83<" in out and ">0.09<" not in out
    assert "0.09 s" in out  # still readable in the hover title


def test_simple_bars_chart():
    chart = {"type": "bars", "unit": "tokens",
             "items": [{"label": "cold", "value": 35792}, {"label": "warm", "value": 43040}]}
    out = chart_html(chart, "r1")
    assert "35,792" in out and "43,040" in out


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
    assert ids == ["concepts", "why", "views", "decisions", "flow", "results", "interview",
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


def test_numbers_differing_only_by_trailing_zeros_match(tmp_path):
    src = _write(tmp_path, "post.md", "# Title\nCompile 0.30 s, graph 4.10 s, flat 4.00 s.\n")
    u = artifact_unit()
    u["sources"] = [{"file": src, "section": "Title"}]
    u["question"] = "Is 0.3 and 4.1 and 4.0 and 2.50 real?"
    u["derived_numbers"] = [{"value": "2.5", "how": "half of five"}]
    u["results"] = []
    assert untraced_numbers(u) == []
    # chart values are floats ("0.3", "4.1"); the source prints "0.30", "4.10"
    u["results"] = [{"chart": {"type": "bars", "unit": "s", "items": [
        {"label": "a", "value": 0.3}, {"label": "b", "value": 4.1}, {"label": "c", "value": 4.0}]}}]
    assert untraced_numbers(u) == []


def test_missing_section_is_reported(tmp_path):
    src = _write(tmp_path, "post.md", "# Title\n")
    u = artifact_unit()
    u["sources"] = [{"file": src, "section": "Title"}, {"file": src, "section": "Nowhere"}]
    assert missing_sections(u) == [f"{src}: Nowhere"]


def test_decision_shows_one_line_and_hides_the_full_reasoning_behind_a_click():
    u = artifact_unit()
    u["decisions"][0]["why"] = "The long full reasoning."
    u["decisions"][0]["why_short"] = "The short reason."
    page = render_page(u)
    card = page.split('id="d-d0"')[1].split('id="d-d1"')[0]
    assert "The short reason." in card.split("<details")[0]
    assert "The long full reasoning." in card.split("<details")[1]
    assert "<summary>Full reasoning and cost</summary>" in card


def test_result_supporting_several_decisions_links_to_each():
    from tests.study_examples import artifact_unit_with_links
    u = artifact_unit_with_links()
    page = render_page(u)
    assert 'href="#d-d0"' in page and 'href="#d-d1"' in page
    brief = render_brief(u)
    assert "- So: see decisions `d0`, `d1`" in brief


def _interval(rows):
    return {"type": "interval", "unit": "s", "zero_label": "no difference",
            "left_label": "B faster", "right_label": "A faster", "rows": rows}


def _x(out, pattern):
    return [float(v) for v in re.findall(pattern, out)]


def test_interval_zero_line_sits_inside_an_interval_that_crosses_zero():
    out = chart_html(_interval([{"label": "B minus C", "estimate": 1.5, "low": -0.5,
                                 "high": 3.25}]), "i0")
    zero = _x(out, r'<line class="zero" x1="([\d.]+)"')[0]
    w = re.search(r'<line class="whisker" x1="([\d.]+)" y1="[\d.]+" x2="([\d.]+)"', out)
    lo, hi = float(w.group(1)), float(w.group(2))
    dot = _x(out, r'<circle class="est" cx="([\d.]+)"')[0]
    assert lo < zero < hi
    assert lo < dot < hi and dot > zero


def test_interval_zero_line_is_left_of_a_positive_interval_and_right_of_a_negative_one():
    out = chart_html(_interval([{"label": "A minus B", "estimate": 10.39, "low": 8.25,
                                 "high": 12.5}]), "i1")
    zero = _x(out, r'<line class="zero" x1="([\d.]+)"')[0]
    dot = _x(out, r'<circle class="est" cx="([\d.]+)"')[0]
    w = re.search(r'<line class="whisker" x1="([\d.]+)" y1="[\d.]+" x2="([\d.]+)"', out)
    assert zero < float(w.group(1)) < dot < float(w.group(2))
    out = chart_html(_interval([{"label": "C minus A", "estimate": -4, "low": -6,
                                 "high": -2}]), "i2")
    zero = _x(out, r'<line class="zero" x1="([\d.]+)"')[0]
    dot = _x(out, r'<circle class="est" cx="([\d.]+)"')[0]
    assert dot < zero


def test_interval_prints_estimate_low_high_and_the_labels():
    out = chart_html(_interval([{"label": "A minus B", "estimate": -10.39, "low": -12.5,
                                 "high": -8.25}]), "i3")
    for shown in (">−10.39 s<", ">−12.5<", ">−8.25<", ">A minus B<", ">no difference<",
                  "B faster", "A faster"):
        assert shown in out
    assert 'aria-label="' in out and "var(--" not in out.split("<svg")[0]
    assert not re.search(r'(fill|stroke)="#', out)  # theme tokens via classes only


def test_interval_text_is_never_outside_the_viewbox():
    out = chart_html(_interval([{"label": "wide", "estimate": 1000.5, "low": 900.25,
                                 "high": 1100.75},
                                {"label": "narrow", "estimate": 0.5, "low": 0.25,
                                 "high": 0.75}]), "i4")
    width = float(re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', out).group(1))
    height = float(re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', out).group(2))
    for m in re.finditer(r'<text class="[^"]*" x="([\d.-]+)" y="([\d.-]+)"'
                         r'(?: text-anchor="(\w+)")?>([^<]*)<', out):
        x, y, anchor, txt = float(m.group(1)), float(m.group(2)), m.group(3), m.group(4)
        w = len(txt) * 8.5
        left = {"end": x - w, "middle": x - w / 2}.get(anchor, x)
        assert left >= 0 and left + w <= width + 0.5, txt
        assert 0 < y <= height, txt


def test_brief_lists_interval_rows():
    u = artifact_unit()
    u["results"][0]["chart"] = _interval([{"label": "A minus B", "estimate": -10.39,
                                           "low": -12.5, "high": -8.25}])
    assert "- A minus B: -10.39 s (interval -12.5 to -8.25)" in render_brief(u)


def test_interval_shades_the_named_side_of_zero_only_when_asked():
    rows = [{"label": "A minus B", "estimate": -10.39, "low": -12.5, "high": 2.0}]
    assert 'class="shade"' not in chart_html(_interval(rows), "i5")
    out = chart_html(dict(_interval(rows), shade="left"), "i5")
    zero = _x(out, r'<line class="zero" x1="([\d.]+)"')[0]
    m = re.search(r'<rect class="shade" x="([\d.]+)" y="[\d.]+" width="([\d.]+)"', out)
    x, w = float(m.group(1)), float(m.group(2))
    assert abs(x + w - zero) < 0.2


def test_interval_values_are_traced_as_unsigned_numbers(tmp_path):
    src = _write(tmp_path, "post.md", "# Title\nDifference -10.39 s, interval [-12.50, -8.25].\n")
    u = artifact_unit()
    u["sources"] = [{"file": src, "section": "Title"}]
    u["results"][0]["chart"] = _interval([{"label": "A minus B", "estimate": -10.39,
                                           "low": -12.5, "high": -8.25}])
    assert untraced_numbers(u) == []
    u["results"][0]["chart"]["rows"][0]["high"] = -8.75
    assert untraced_numbers(u) == ["8.75"]


def test_interval_stays_narrow_enough_to_read_on_a_phone():
    # 309 px of card on a 375 px phone; 15 px phone text must render at >= 11 px.
    out = chart_html(dict(_interval([{"label": "(A-B) minus (B-C)", "estimate": -10.39,
                                      "low": -12.5, "high": -8.25}]),
                          left_label="weights cache saves more",
                          right_label="compile cache saves more"), "i6")
    width = float(re.search(r'viewBox="0 0 ([\d.]+)', out).group(1))
    assert 309 / width * 15 >= 11


def test_stacked_chart_lists_what_changed_between_the_bars():
    chart = dict(artifact_unit()["results"][0]["chart"],
                 deltas=[{"between": "A → C", "text": "Compile <time> nearly vanishes."}])
    out = chart_html(chart, "r0")
    tail = out.split("</svg>")[1]
    assert "What changed between the bars" in tail
    assert "A → C" in tail and "Compile &lt;time&gt; nearly vanishes." in tail
    assert "What changed" not in chart_html(artifact_unit()["results"][0]["chart"], "r0")


def test_highlight_greys_out_the_other_segments_and_their_legend_chips():
    chart = dict(artifact_unit()["results"][0]["chart"], highlight=["compile"])
    out = chart_html(chart, "r0")
    segs = re.findall(r'<rect class="seg ([^"]+)"', out)
    assert segs == ["s0 dim", "s1", "s0 dim", "s1"]  # load, compile per bar
    chips = re.findall(r'<span class="chip ([^"]+)"></span>([^<]+)<', out)
    assert chips == [("s0 dim", "load"), ("s1", "compile")]
    texts = re.findall(r'<text class="segtext ([^"]+)"', out)
    assert all("dim" in t for t in texts if t.startswith("s0"))
    plain = chart_html(artifact_unit()["results"][0]["chart"], "r0")
    assert " dim" not in plain


def test_brief_lists_deltas():
    u = artifact_unit()
    u["results"][0]["chart"]["deltas"] = [{"between": "A → C", "text": "Compile vanishes."}]
    assert "- Changed A → C: Compile vanishes." in render_brief(u)


# ---- the relationship map ----

from study.map import barycentre_order, map_section
from tests.study_examples import artifact_unit_with_links, prereq_unit


def _dom_ids(html):
    """content ref -> DOM id, per node kind."""
    out = {}
    for kind, dom, ref in re.findall(
            r'<button type="button" class="mnode (\w+)" id="(m-[\w-]+)" data-ref="([^"]*)"', html):
        out[(kind, ref)] = dom
    return out


def _edges(html):
    return set(re.findall(r'<path class="medge" data-from="([\w-]+)" data-to="([\w-]+)"', html))


def test_map_only_when_requirements_have_ids():
    assert 'id="map"' not in render_page(artifact_unit())
    assert 'id="map"' not in render_page(prereq_unit())
    assert map_section(artifact_unit()) == ""
    page = render_page(artifact_unit_with_links())
    assert '<section id="map"><h2>How the pieces connect</h2>' in page
    assert '<a href="#map">Map</a>' in page


def test_map_sits_after_results_and_before_interview():
    ids = re.findall(r'<section id="([\w-]+)"', render_page(artifact_unit_with_links()))
    assert ids.index("results") + 1 == ids.index("map") == ids.index("interview") - 1


def test_map_css_and_js_ship_only_with_a_map():
    assert ".mnode" not in render_page(artifact_unit())
    page = render_page(artifact_unit_with_links())
    assert page.count("<style>") == 1 and page.count("<script>") == 1
    assert ".mnode" in page and "mgrid" in page.split("<script>")[1]


def test_every_link_in_the_content_is_an_edge_and_nothing_else_is():
    u = artifact_unit_with_links()
    html = map_section(u)
    dom = _dom_ids(html)
    expected = set()
    for d in u["decisions"]:
        for s in d["serves"]:
            expected.add((dom[("req", s["req"])], dom[("dec", d["id"])]))
        for k in d["uses"]:
            expected.add((dom[("dec", d["id"])], dom[("con", k["concept"])]))
    for i, r in enumerate(u["results"]):
        so = r.get("so", [])
        for d in [so] if isinstance(so, str) else so:
            expected.add((dom[("dec", d)], dom[("res", str(i))]))
    assert _edges(html) == expected
    assert len(expected) == 5 + 3 + 2  # serves, uses, so


def test_every_node_has_a_panel_with_its_one_line_text_and_link_reasons():
    u = artifact_unit_with_links()
    html = map_section(u)
    dom = _dom_ids(html)

    def panel(kind, ref):
        return html.split(f'<template id="mp-{dom[(kind, ref)]}">')[1].split("</template>")[0]

    assert "Split one cold start into named phases." in panel("req", "R1")
    assert "d1 meets R1." in panel("req", "R1")  # the because of a serves link
    assert "A short reason." in panel("dec", "d0")  # why_short
    assert "d0 is built on arms." in panel("dec", "d0")
    assert "Loading weights is most of a cold start." in panel("res", "0")  # takeaway
    assert "One set-up under test." in panel("con", "arms")  # plain
    assert "no decision rests on it" in panel("res", "1")  # so_none_reason


def test_unlinked_requirement_shows_its_reason():
    u = artifact_unit_with_links()
    html = map_section(u)
    dom = _dom_ids(html)
    tpl = html.split(f'<template id="mp-{dom[("req", "R3")]}">')[1].split("</template>")[0]
    assert "Served by the process: the flow&#x27;s last step, not a decision." in tpl
    node = re.search(rf'id="{dom[("req", "R3")]}".*?</button>', html, re.DOTALL).group(0)
    assert "No decision" in node


def test_node_text_is_escaped():
    u = artifact_unit_with_links()
    u["requirements"][0]["short"] = "<b>bold</b>"
    u["decisions"][0]["serves"][0]["because"] = "<script>x</script>"
    u["concepts"][0]["plain"] = "<img src=x>"
    html = map_section(u)
    assert "<b>bold</b>" not in html and "&lt;b&gt;bold&lt;/b&gt;" in html
    assert "<script>x" not in html and "<img src=x>" not in html


def test_labels_fall_back_to_truncated_text_and_titles():
    u = artifact_unit_with_links()
    del u["requirements"][0]["short"]
    u["requirements"][0]["text"] = "A requirement whose text runs well past forty characters."
    del u["decisions"][0]["short"]
    html = map_section(u)
    assert "A requirement whose text runs well past…" in html
    assert '<span class="mlab">Decision 0</span>' in html


def test_narrow_list_names_each_nodes_links():
    html = map_section(artifact_unit_with_links())
    dom = _dom_ids(html)
    node = re.search(rf'id="{dom[("req", "R1")]}".*?</button>', html, re.DOTALL).group(0)
    assert "Links: D1 · D2 · D4" in node


def test_barycentre_order_is_deterministic_and_follows_neighbours():
    # item -> positions of its neighbours in the fixed column
    assert barycentre_order(["a", "b", "c", "d"],
                            {"a": [3], "b": [0], "c": [], "d": [0, 3]}) == ["b", "d", "a", "c"]
    # ties keep the input order
    assert barycentre_order(["x", "y"], {"x": [1], "y": [1]}) == ["x", "y"]


def test_right_column_interleaves_results_and_concepts_by_their_decisions():
    html = map_section(artifact_unit_with_links())
    right = html.split('class="mcol mcol-right"')[1]
    order = re.findall(r'class="mnode (res|con)" id="[\w-]+" data-ref="([^"]*)"', right)
    # F1 rests on D1,D2 (0.5); arms is used by D1,D4 (1.5); contrast by D3 (2); F2 by none.
    assert order == [("res", "0"), ("con", "arms"), ("con", "contrast"), ("res", "1")]


def test_requirements_are_ordered_by_the_decisions_that_serve_them():
    u = artifact_unit_with_links()
    for d in u["decisions"]:
        d["serves"] = [{"req": "R2", "because": "x"}]
    u["decisions"][3]["serves"] = [{"req": "R1", "because": "x"}]
    u["decisions"][0]["serves"] = [{"req": "R2", "because": "x"}]
    left = map_section(u).split('class="mcol mcol-req"')[1].split('class="mcol mcol-dec"')[0]
    assert re.findall(r'data-ref="(R\d)"', left) == ["R2", "R1", "R3"]


def test_nav_follows_the_section_order():
    page = render_page(artifact_unit_with_links())
    sections = re.findall(r'<section id="([\w-]+)"', page)
    nav = re.findall(r'<a href="#([\w-]+)">', page.split('<nav class="pills">')[1].split("</nav>")[0])
    assert nav == sections == ["concepts", "why", "views", "decisions", "flow", "results", "map",
                               "interview", "recall", "sources"]


def test_hero_states_the_question_and_the_answer_first():
    u = artifact_unit_with_links()
    hero = render_page(u).split('<header class="hero">')[1].split("</header>")[0]
    assert '<p class="lead">Does the example hold?</p>' in hero
    assert "Answer first" in hero and "Thirty seconds." in hero
    chips = re.findall(r'<a class="achip" href="#(r-\d+)">([^<]+)</a>', hero)
    assert chips == [("r-0", "Where the time goes"), ("r-1", "A side result"),]


def test_answer_strip_needs_a_pitch_and_results():
    u = artifact_unit()
    u["results"] = []
    hero = render_page(u).split('<header class="hero">')[1].split("</header>")[0]
    assert "Does the example hold?" in hero and "Answer first" not in hero


def test_requirements_section_is_titled_and_shows_ids():
    page = render_page(artifact_unit_with_links())
    why = page.split('<section id="why">')[1].split("</section>")[0]
    assert why.startswith("<h2>Requirements that drove everything</h2>")
    assert '<span class="rcode">R1</span>' in why
    assert "Does the example hold?" not in why


# ---- review fixes ----

def _media(css, query):
    return css.split(f"@media ({query})")[1].split("}}")[0]


def test_rows_are_a_two_column_grid_that_stacks_on_phones():
    from study.page import CSS
    assert ".row{display:grid;grid-template-columns:104px 1fr;" in CSS
    assert ".row{display:block}" in _media(CSS, "max-width:600px")


def test_phone_nav_is_one_scrolling_row():
    from study.page import CSS
    phone = _media(CSS, "max-width:600px")
    assert "nav.pills{flex-wrap:nowrap;overflow-x:auto" in phone
    assert "nav.pills a{flex:none" in phone


def test_decision_card_drops_the_chose_row_but_the_brief_keeps_it():
    u = artifact_unit()
    assert "<b>Chose</b>" not in render_page(u)
    assert 'class="opt chosen"' in render_page(u)
    assert "**Chosen:** Option one" in render_brief(u)


def test_brief_requirement_lines_have_no_double_period():
    u = artifact_unit()
    u["requirements"][0]["text"] = "Change exactly one thing."
    brief = render_brief(u)
    assert "- Change exactly one thing. *Why:* Because 0." in brief
    assert "- Requirement 1. *Why:* Because 1." in brief
    assert ".." not in brief


def test_brief_points_to_the_page_for_sources():
    u = artifact_unit()
    brief = render_brief(u)
    assert "## Sources" not in brief and "docs/post.md" not in brief
    assert "\nSources: see the page\n" in brief


def test_brief_relationships_only_with_links():
    assert "## Relationships" not in render_brief(artifact_unit())
    brief = render_brief(artifact_unit_with_links())
    heads = [ln for ln in brief.splitlines() if ln.startswith("## ")]
    assert heads.index("## Relationships") == heads.index("## Core decisions") + 1
    rel = brief.split("## Relationships")[1].split("\n## ")[0]
    assert "- R1: Split one cold start into named phases." in rel
    assert "  - `d1` Decision 1: d1 meets R1." in rel
    assert "  - No decision: Served by the process: the flow's last step, not a decision." in rel
    assert "- `d0` Decision 0 uses Arm: d0 is built on arms." in rel
    assert "- A result → `d0` Decision 0, `d1` Decision 1" in rel
    assert "- A side result → no decision: Reported for completeness; no decision rests on it." in rel


# ---- comprehension-review fixes ----

def test_concept_cards_are_wide_and_stack_each_label_above_its_text():
    from study.page import CSS
    from tests.study_examples import prereq_unit
    # 360 px minimum: three columns in the 1448 px content box of a 1560 px page, not four.
    assert ".cgrid{grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr))}" in CSS
    assert ".crow b{display:block;" in CSS
    concepts = render_page(prereq_unit()).split('<section id="concepts">')[1].split("</section>")[0]
    assert '<div class="grid cgrid">' in concepts
    assert 'class="row"' not in concepts
    assert concepts.count('<div class="crow"><b>Like</b>') == 3
    assert concepts.count('<div class="crow"><b>Matters</b>') == 3
    # decision cards keep their side-by-side rows
    decisions = render_page(artifact_unit()).split('<section id="decisions">')[1]
    assert '<div class="row"><b>Problem</b>' in decisions


def test_concept_with_an_id_gets_an_anchor_and_every_page_id_is_unique():
    u = artifact_unit_with_links()
    u["concepts"].append({"id": 'q"x', "term": "Quoted", "plain": "Plain."})  # escaped
    u["concepts"].append({"term": "No id", "plain": "Plain."})
    page = render_page(u)
    concepts = page.split('<section id="concepts">')[1].split("</section>")[0]
    assert '<div class="card" id="c-arms">' in concepts
    assert '<div class="card" id="c-contrast">' in concepts
    assert '<div class="card" id="c-q&quot;x">' in concepts
    assert concepts.count('<div class="card"') == 4 and concepts.count(' id="') == 3
    ids = re.findall(r' id="([^"]+)"', page)
    assert len(ids) == len(set(ids))
    from study.page import CSS
    assert "section,.card[id]{scroll-margin-top:64px}" in CSS


def test_prereq_brief_titles_its_views_without_c4():
    from tests.study_examples import prereq_unit
    brief = render_brief(prereq_unit())
    assert "\n## Views\n" in brief and "(C4)" not in brief
    assert "\n## System views (C4)\n" in render_brief(artifact_unit())


def test_phone_list_keeps_focus_emphasis_and_marks_external_nodes():
    out = diagram_html(artifact_unit()["views"][0], "u")
    text = out.split('class="diagram-text"')[1].split("<ol>")[0]
    items = re.findall(r"<li>(.*?)</li>", text)
    # Author is a person, Harness the focus, GPU worker external
    assert items[1].startswith('<strong>Harness</strong> <small class="kmark">key step</small>')
    assert items[2].startswith("GPU worker <small>(external)</small>")
    assert "<strong>" not in items[0] and "<strong>" not in items[2]
    from study.page import CSS
    assert ".kmark{" in CSS


def _texts(out):
    """(classes, x, y, anchor, text) for every <text> in a chart."""
    return [(m.group(1), float(m.group(2)), float(m.group(3)), m.group(4) or "start", m.group(5))
            for m in re.finditer(r'<text class="([^"]*)" x="([\d.-]+)" y="([\d.-]+)"'
                                 r'(?: text-anchor="(\w+)")?>([^<]*)<', out)]


def test_interval_against_zero_keeps_each_side_label_on_its_own_side():
    out = chart_html(dict(_interval([{"label": "(A − B) − (B − C), total cold start",
                                      "estimate": -10.39, "low": -20.30, "high": -5.54}]),
                          left_label="compile cache saves more",
                          right_label="weight cache saves more"), "i7")
    zero = _x(out, r'<line class="zero" x1="([\d.]+)"')[0]
    width = float(re.search(r'viewBox="0 0 ([\d.]+)', out).group(1))
    texts = _texts(out)
    left = [t for t in texts if "sidel" in t[0]]
    right = [t for t in texts if "sider" in t[0]]
    assert left and right
    for _, x, _, anchor, txt in left:
        assert anchor == "end" and x <= zero, txt  # right edge of the left label
    for _, x, _, anchor, txt in right:
        assert anchor == "start" and x >= zero, txt
        assert x + len(txt) * 8.5 <= width + 0.5, txt
    assert "weight cache saves more" in " ".join(t[4] for t in right)
    # the axis runs past zero, so the empty side is visibly there
    axis_end = float(re.search(r'<line class="axis" x1="[\d.]+" y1="[\d.]+" x2="([\d.]+)"',
                               out).group(1))
    assert axis_end > zero + 20
    assert 309 / width * 15 >= 11  # still readable on a phone


def test_dimmed_segment_still_prints_its_value_in_a_muted_colour():
    # a flat 4 s phase in an ~80 s bar is ~15 px wide: it must still show its "4"
    chart = {"type": "stacked_bars", "unit": "s", "highlight": ["load"], "bars": [
        {"label": "A", "segments": [{"name": "load", "value": 45.83},
                                    {"name": "graph", "value": 4.0},
                                    {"name": "rest", "value": 30.0}]}]}
    out = chart_html(chart, "r9")
    assert re.search(r'<text class="segtext s1 dim" [^>]*>4</text>', out)
    from study.page import CSS
    assert ".segtext.dim{fill:var(--muted)}" in CSS
