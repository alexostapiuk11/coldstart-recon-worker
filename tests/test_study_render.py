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
    # the row has two decimals (-10.39), so -12.5 prints as authored precision: -12.50
    for shown in (">−10.39 s<", ">−12.50<", ">−8.25<", ">A minus B<", ">no difference<",
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


def test_result_arithmetic_is_a_row_under_read_it_as_on_page_and_in_brief():
    u = artifact_unit()
    u["results"][0]["arithmetic"] = "45.83 - 30.35 = 15.48 s"
    page = render_page(u)
    card = page.split('id="r-0"')[1].split('<div class="card"')[0]
    read_as = card.index("<b>Read it as</b>")
    computed = card.index("<b>How it is computed</b><div>45.83 - 30.35 = 15.48 s</div>")
    assert read_as < computed
    brief = render_brief(u)
    result = brief.split(f"### {u['results'][0]['title']}")[1]
    assert result.index("- Read it as:") < result.index(
        "- How it is computed: 45.83 - 30.35 = 15.48 s")
    assert "How it is computed" not in render_page(artifact_unit())
    assert "How it is computed" not in render_brief(artifact_unit())


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
            expected.add((dom[("con", k["concept"])], dom[("dec", d["id"])]))
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


def test_labels_are_card_titles_never_short_or_truncated():
    u = artifact_unit_with_links()
    del u["requirements"][0]["short"]
    u["requirements"][0]["text"] = "A requirement whose text runs well past forty characters."
    html = map_section(u)
    assert '<span class="mlab">A requirement whose text runs well past forty characters.</span>' in html
    assert "…" not in html
    # decisions, results and concepts ignore `short` in the map
    assert '<span class="mlab">Decision 0</span>' in html and "Short d0" not in html
    assert '<span class="mlab">A result</span>' in html and "Where the time goes" not in html
    assert '<span class="mlab">Arm</span>' in html and "Arms A, B, C" not in html


def _heading(page, anchor):
    """(code, title) of the card with this id."""
    h3 = re.search(rf' id="{re.escape(anchor)}"><h3>(.*?)</h3>', page).group(1)
    m = re.fullmatch(r'<span class="code">([^<]+)</span>(.*)', h3)
    return m.group(1), m.group(2)


def test_every_map_label_and_code_equals_its_card_heading():
    page = render_page(artifact_unit_with_links())
    prefix = {"req": "req-", "dec": "d-", "res": "r-", "con": "c-"}
    nodes = re.findall(r'class="mnode (\w+)" id="[\w-]+" data-ref="([^"]*)"[^>]*>'
                       r'<span class="mcode">([^<]+)</span><span class="mlab">([^<]+)</span>', page)
    assert len(nodes) == 3 + 4 + 2 + 2
    for kind, ref, code, label in nodes:
        assert _heading(page, prefix[kind] + ref) == (code, label), (kind, ref)


def test_narrow_list_names_each_nodes_links():
    html = map_section(artifact_unit_with_links())
    dom = _dom_ids(html)
    node = re.search(rf'id="{dom[("req", "R1")]}".*?</button>', html, re.DOTALL).group(0)
    assert "Links: D1 · D2 · D4" in node
    # a decision lists its links in lane order: requirements, concepts, then results
    node = re.search(rf'id="{dom[("dec", "d0")]}".*?</button>', html, re.DOTALL).group(0)
    assert "Links: R1 · C1 · F1" in node


def test_barycentre_order_is_deterministic_and_follows_neighbours():
    # item -> positions of its neighbours in the fixed column
    assert barycentre_order(["a", "b", "c", "d"],
                            {"a": [3], "b": [0], "c": [], "d": [0, 3]}) == ["b", "d", "a", "c"]
    # ties keep the input order
    assert barycentre_order(["x", "y"], {"x": [1], "y": [1]}) == ["x", "y"]


def _column(html, name):
    return html.split(f'class="mcol mcol-{name}"')[1].split('class="mcol ')[0]


def _kinds(html):
    return re.findall(r'class="mnode (\w+)" id="[\w-]+" data-ref="([^"]*)"', html)


def test_lanes_left_requirements_then_concepts_middle_decisions_right_results():
    html = map_section(artifact_unit_with_links())
    left, mid, right = (_column(html, n) for n in ("left", "dec", "right"))
    assert [k for k, _ in _kinds(left)] == ["req"] * 3 + ["con"] * 2
    heads = [re.sub(r"<[^>]+>", "", h) for h in re.findall(r'<h3 class="mhead[^"]*">(.*?)</h3>', html)]
    assert heads == ["Requirements (why)", "Key concepts (vocabulary)",
                     "Decisions (what was decided)", "Results (what came out)"]
    assert [k for k, _ in _kinds(mid)] == ["dec"] * 4
    assert _kinds(right) == [("res", "0"), ("res", "1")]
    # the phone list stacks the columns in DOM order: Requirements, Concepts, Decisions, Results
    order = [k for k, _ in _kinds(html)]
    assert order == ["req"] * 3 + ["con"] * 2 + ["dec"] * 4 + ["res"] * 2


def test_concepts_follow_barycentre_and_results_keep_content_order():
    u = artifact_unit_with_links()
    u["decisions"][2]["uses"] = []
    u["decisions"][0]["uses"] = [{"concept": "contrast", "because": "x"},
                                 {"concept": "arms", "because": "x"}]
    u["decisions"][3]["uses"] = [{"concept": "arms", "because": "x"}]
    # contrast: D1 only (0); arms: D1 and D4 (1.5)
    u["results"][0]["so"] = "d3"
    u["results"][1] = dict(u["results"][1], so="d0")
    del u["results"][1]["so_none_reason"]
    html = map_section(u)
    assert [r for k, r in _kinds(_column(html, "left")) if k == "con"] == ["contrast", "arms"]
    assert _kinds(_column(html, "right")) == [("res", "0"), ("res", "1")]


def test_panels_use_the_card_words_for_each_link_group():
    html = map_section(artifact_unit_with_links())
    dom = _dom_ids(html)

    def heads(kind, ref):
        tpl = html.split(f'<template id="mp-{dom[(kind, ref)]}">')[1].split("</template>")[0]
        return re.findall(r"<h4>([^<]+)</h4>", tpl)

    assert heads("res", "0") == ["Rests on"]
    assert heads("req", "R1") == ["Answered by"]
    assert heads("dec", "d0") == ["Serves", "Uses", "Seen in"]
    assert heads("con", "arms") == ["Used by"]
    assert "Decisions it supports" not in html


def test_map_has_a_lane_legend():
    html = map_section(artifact_unit_with_links())
    assert ("Left: what drove the work and the vocabulary. Middle: what was decided. "
            "Right: what came out.") in html


def test_requirements_are_ordered_by_the_decisions_that_serve_them():
    u = artifact_unit_with_links()
    for d in u["decisions"]:
        d["serves"] = [{"req": "R2", "because": "x"}]
    u["decisions"][3]["serves"] = [{"req": "R1", "because": "x"}]
    u["decisions"][0]["serves"] = [{"req": "R2", "because": "x"}]
    left = _column(map_section(u), "left")
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
    assert '<h3><span class="code">R1</span>Split the start into phases</h3>' in why
    assert "<div>Split one cold start into named phases.</div>" in why
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


def _stacked(*names):
    return {"type": "stacked_bars", "unit": "s", "bars": [
        {"label": "A", "segments": [{"name": n, "value": 10.0} for n in names]}]}


def test_a_segment_name_keeps_its_colour_in_every_chart_of_a_page():
    u = artifact_unit()
    first = dict(u["results"][0], chart=_stacked("Weights", "Everything else"))
    second = dict(u["results"][0], title="Second",
                  chart=_stacked("Platform", "Everything else", "Compile"))
    u["results"] = [first, second]
    page = render_page(u)
    chips = re.findall(r'<span class="chip (s\d)"></span>([^<]+)<', page)
    colour = {}
    for slot, name in chips:
        assert colour.setdefault(name, slot) == slot, name  # same name, same colour
    # Weights and Compile are canonical phases with fixed slots (7 and 1); the other two
    # names take the lowest slots no name on the page uses yet.
    assert colour == {"Weights": "s7", "Everything else": "s0", "Platform": "s2",
                      "Compile": "s1"}
    segs = re.findall(r'<rect class="seg (s\d)"[^>]*><title>([^:]+):', page)
    assert all(colour[n] == s for s, n in segs)
    # a chart on its own still colours by its own order
    alone = chart_html(second["chart"], "r1")
    assert re.findall(r'<span class="chip (s\d)"></span>', alone) == ["s0", "s1", "s2"]


def test_segment_slots_avoid_a_clash_inside_one_chart_once_eight_are_used():
    from study.svg import segment_slots
    nine = [f"n{i}" for i in range(9)]
    slots = segment_slots([_stacked(*nine[:8]), _stacked("n0", "n8")])
    assert [slots[n] for n in nine[:8]] == list(range(8))
    assert slots["n8"] != slots["n0"]


def test_results_heading_is_in_pictures_for_a_prereq():
    from tests.study_examples import prereq_unit
    u = prereq_unit()
    u["results"] = artifact_unit()["results"]
    del u["results"][0]["so"]
    assert '<section id="results"><h2>In pictures</h2>' in render_page(u)
    assert '<section id="results"><h2>Results, as meaning</h2>' in render_page(artifact_unit())


# ---- links on the cards ----

def _card(page, anchor):
    """The HTML of the card whose id is `anchor`, up to the next card."""
    return page.split(f'id="{anchor}"')[1].split('<div class="card')[0]


def _hrefs(html):
    return re.findall(r'href="#([^"]+)"', html)


def test_traced_cards_carry_codes_and_link_rows():
    page = render_page(artifact_unit_with_links())
    r1 = _card(page, "req-R1")
    assert '<span class="code">R1</span>' in r1
    assert "Answered by:" in r1 and _hrefs(r1) == ["d-d0", "d-d1", "d-d3"]
    r3 = _card(page, "req-R3")
    assert "Answered by:" in r3 and "Served by the process" in r3 and not _hrefs(r3)
    d1 = _card(page, "d-d1")
    assert '<span class="code">D2</span>' in d1
    serves = d1.split("Serves:")[1].split("</div>")[0]
    assert _hrefs(serves) == ["req-R1", "req-R2"]
    assert "R1</span> Split the start into phases" in serves
    seen = d1.split("Seen in:")[1].split("</div>")[0]
    assert _hrefs(seen) == ["r-0"] and "F1</span> A result" in seen
    assert "Seen in:" not in _card(page, "d-d2")  # no result rests on d2
    f1 = _card(page, "r-0")
    assert '<span class="code">F1</span>' in f1
    assert "Rests on:" in f1 and "So:" not in f1
    assert _hrefs(f1.split("Rests on:")[1]) == ["d-d0", "d-d1"]
    f2 = _card(page, "r-1")
    assert "Rests on:" in f2 and "no decision rests on it" in f2
    c1 = _card(page, "c-arms")
    assert '<span class="code">C1</span>' in c1
    assert _hrefs(c1.split("Used by:")[1]) == ["d-d0", "d-d3"]
    assert '<span class="code">C2</span>' in _card(page, "c-contrast")


def test_every_card_link_lands_on_an_existing_unique_id():
    page = render_page(artifact_unit_with_links())
    ids = re.findall(r' id="([^"]+)"', page)
    assert len(ids) == len(set(ids))
    for target in _hrefs(page):
        assert target in ids, target


def test_requirement_anchor_is_escaped():
    u = artifact_unit_with_links()
    u["requirements"][2]["id"] = 'R"3'
    page = render_page(u)
    assert 'id="req-R&quot;3"' in page


def test_untraced_cards_render_as_before():
    page = render_page(artifact_unit())
    for marker in ('class="code"', "Answered by", "Serves:", "Seen in:", "Rests on:",
                   "Used by:", 'id="req-'):
        assert marker not in page, marker
    assert '<div class="callout">So: <a href="#d-d0">Decision 0</a></div>' in page


# ---- percentile chart ----

def _pct(**extra):
    return dict({"type": "percentiles", "unit": "s",
                 "rows": [{"label": "A", "values": [{"name": "p50", "value": 81.1},
                                                    {"name": "p90", "value": 96.3},
                                                    {"name": "p95", "value": 96.4}],
                           "max_label": {"text": "largest run", "value": 148.2}},
                          {"label": "B", "values": [{"name": "p50", "value": 81.1},
                                                    {"name": "p90", "value": 90.0}]}]}, **extra)


def _marks(out):
    """(percentile name, row label, x) for every percentile mark."""
    return [(m.group(3), m.group(2), float(m.group(1))) for m in re.finditer(
        r'class="pdot pk\d" data-x="([\d.]+)"[^>]*><title>([^:]+): (\w+)', out)]


def test_percentiles_share_one_axis_and_scale_by_value():
    out = chart_html(_pct(), "p0")
    xs = {(row, name): x for name, row, x in _marks(out)}
    assert xs[("A", "p50")] < xs[("A", "p90")] < xs[("A", "p95")]
    assert xs[("A", "p50")] == xs[("B", "p50")]  # same value, same x, on every row
    # the axis is linear from zero: x is proportional to value past the origin
    x0 = float(re.search(r'<line class="paxis" x1="([\d.]+)"', out).group(1))
    ratio = (xs[("A", "p95")] - x0) / (xs[("A", "p50")] - x0)
    assert abs(ratio - 96.4 / 81.1) < 0.01
    # one range line per row, from its lowest to its highest percentile
    lines = re.findall(r'<line class="prange" x1="([\d.]+)" y1="[\d.]+" x2="([\d.]+)"', out)
    assert [(float(a), float(b)) for a, b in lines] == [
        (xs[("A", "p50")], xs[("A", "p95")]), (xs[("B", "p50")], xs[("B", "p90")])]


def test_percentile_max_label_is_a_hollow_marker_inside_the_axis():
    out = chart_html(_pct(), "p1")
    m = re.search(r'<circle class="pmax" cx="([\d.]+)"', out)
    assert m and float(m.group(1)) > max(x for _, _, x in _marks(out))
    assert ">largest run 148.2<" in out
    ax = re.search(r'<line class="paxis" x1="[\d.]+" y1="[\d.]+" x2="([\d.]+)"', out)
    assert float(ax.group(1)) >= float(m.group(1))
    assert "pmax" not in chart_html(_pct(rows=[_pct()["rows"][1]]), "p1")


def test_percentile_labels_name_each_mark_and_never_collide():
    out = chart_html(_pct(), "p2")
    texts = _texts(out)
    for shown in ("p50 81.1", "p90 96.3", "p95 96.4", "p90 90"):
        assert shown in [t[4] for t in texts], shown
    width = float(re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', out).group(1))
    spans = []
    for cls, x, y, anchor, txt in texts:
        w = len(txt) * 8.5
        left = {"end": x - w, "middle": x - w / 2}.get(anchor, x)
        assert left >= 0 and left + w <= width + 0.5, txt
        spans.append((y, left, left + w, txt))
    for i, a in enumerate(spans):
        for b in spans[i + 1:]:
            if abs(a[0] - b[0]) < 14:  # same line of text
                assert a[2] <= b[1] or b[2] <= a[1], (a[3], b[3])


def test_percentile_chart_has_ticks_aria_and_theme_tokens_only():
    out = chart_html(_pct(), "p3")
    ticks = [t[4] for t in _texts(out) if "ptick" in t[0]]
    assert ticks[0] == "0" and ticks[-1].endswith(" s") and len(ticks) >= 3
    label = re.search(r'aria-label="([^"]+)"', out).group(1)
    assert "A: p50 81.1, p90 96.3, p95 96.4; largest run 148.2" in label
    assert not re.search(r'(fill|stroke)="#', out)
    marks = re.findall(r'class="pdot (pk\d)"', out)
    assert marks[:3] == ["pk0", "pk1", "pk2"]  # one style per percentile name
    width = float(re.search(r'viewBox="0 0 ([\d.]+)', out).group(1))
    assert 309 / width * 14 >= 11  # phone text stays readable
    from study.page import CSS
    for k in range(4):
        assert f".pk{k}{{fill:var(--c" in CSS


def test_percentile_note_prints_under_the_chart():
    out = chart_html(_pct(note="One run was **far** slower."), "p4")
    assert '<p class="cnote">One run was <strong>far</strong> slower.</p>' in out.split("</svg>")[1]


def test_brief_lists_percentile_rows_and_note():
    u = artifact_unit()
    u["results"][0]["chart"] = _pct(note="One run was far slower.")
    brief = render_brief(u)
    assert "- A: p50 81.1, p90 96.3, p95 96.4 (s); largest run 148.2 s" in brief
    assert "- B: p50 81.1, p90 90.0 (s)" in brief
    assert "- Note: One run was far slower." in brief


def test_percentile_values_are_traced(tmp_path):
    src = _write(tmp_path, "post.md", "# Title\np50 81.1, p90 96.3, p95 96.4, p90 90.0, max 148.2\n")
    u = artifact_unit()
    u["sources"] = [{"file": src, "section": "Title"}]
    u["results"][0]["chart"] = _pct()
    assert untraced_numbers(u) == []
    u["results"][0]["chart"]["rows"][0]["max_label"]["value"] = 150.5
    assert untraced_numbers(u) == ["150.5"]


# ---- stacked chart: merge and ghost ----

def _three():
    return {"type": "stacked_bars", "unit": "s", "bars": [
        {"label": "B", "segments": [{"name": "load", "value": 30.35},
                                    {"name": "compile", "value": 18.79},
                                    {"name": "rest", "value": 8.0}]},
        {"label": "C", "segments": [{"name": "load", "value": 21.34},
                                    {"name": "compile", "value": 0.33},
                                    {"name": "rest", "value": 8.0}]}]}


def _segs(out):
    """(name, x, width) per drawn segment, in order."""
    return [(m.group(3), float(m.group(1)), float(m.group(2))) for m in re.finditer(
        r'<rect class="seg [^"]+" x="([\d.]+)" y="[\d.]+" width="([\d.]+)"[^>]*><title>([^:]+):',
        out)]


def test_merge_draws_one_segment_with_the_summed_value_and_one_legend_entry():
    out = chart_html(dict(_three(), merge=[{"names": ["compile", "rest"], "label": "Other"}]), "m0")
    segs = _segs(out)
    assert [n for n, _, _ in segs] == ["load", "Other", "load", "Other"]
    plain = _segs(chart_html(_three(), "m0"))
    # the merged width is the two segments' widths together (each loses a 2 px gap once)
    assert abs(segs[1][2] - (plain[1][2] + plain[2][2] + 2)) < 0.3
    assert ">26.79<" in out  # 18.79 + 8.0, printed inside
    assert "Other: 26.79 s (compile 18.79 + rest 8)" in out
    chips = re.findall(r'<span class="chip [^"]+"></span>([^<]+)<', out)
    assert chips == ["load", "Other"]


def test_merge_keeps_one_colour_per_drawn_name_across_charts():
    from study.svg import segment_slots
    merged = dict(_three(), merge=[{"names": ["compile", "rest"], "label": "Other"}])
    assert segment_slots([merged]) == {"load": 0, "Other": 1}


def test_ghost_outlines_where_the_segment_sat_in_the_other_bar():
    out = chart_html(dict(_three(), ghost={"segment": "compile", "from_bar": "B", "on_bar": "C"}),
                     "g0")
    segs = _segs(out)
    b_compile = segs[1]
    c_compile = segs[4]
    m = re.search(r'<rect class="ghost" x="([\d.]+)" y="([\d.]+)" width="([\d.]+)"', out)
    gx, gy, gw = (float(v) for v in m.groups())
    assert abs(gx - c_compile[1]) < 0.11  # starts where compile starts in C
    assert abs(gw - (b_compile[2] + 2)) < 0.3  # as wide as compile was in B
    c_y = float(re.findall(r'<rect class="seg [^"]+" x="[\d.]+" y="([\d.]+)"', out)[3])
    assert abs(gy - c_y) < 2  # on C's row
    assert ">was 18.79 s in B<" in out
    assert not re.search(r'(fill|stroke)="#', out)
    from study.page import CSS
    assert ".ghost{fill:none;stroke:var(--fg)" in CSS


def test_ghost_caption_gets_its_own_room_and_stays_in_the_viewbox():
    out = chart_html(dict(_three(), ghost={"segment": "compile", "from_bar": "B", "on_bar": "C"}),
                     "g1")
    plain = chart_html(_three(), "g1")
    h = float(re.search(r'viewBox="0 0 [\d.]+ ([\d.]+)"', out).group(1))
    assert h > float(re.search(r'viewBox="0 0 [\d.]+ ([\d.]+)"', plain).group(1))
    width = float(re.search(r'viewBox="0 0 ([\d.]+)', out).group(1))
    for cls, x, y, anchor, txt in _texts(out):
        w = len(txt) * 8.5
        left = {"end": x - w, "middle": x - w / 2}.get(anchor, x)
        assert left >= 0 and left + w <= width + 0.5 and y <= h, txt


def test_brief_notes_merge_and_ghost():
    u = artifact_unit()
    u["results"][0]["chart"] = dict(_three(), merge=[{"names": ["compile", "rest"],
                                                       "label": "Other"}],
                                    ghost={"segment": "load", "from_bar": "B", "on_bar": "C"})
    brief = render_brief(u)
    assert "- B: load 30.35, compile 18.79, rest 8.0 (s)" in brief
    assert "- Drawn as one segment, Other: compile + rest" in brief
    assert "- On bar C, a dashed outline shows where load sat in B (30.35 s)" in brief


# ---- cross-page links ----

import pytest

from study.schema import ContentError
from study.text import resolve_links


def _linked_unit(**top):
    u = artifact_unit()
    u.update(top)
    u["decisions"][0]["why_short"] = "Built on the [KV <cache>](p1:kvcache), see **this**."
    u["decisions"][0]["why"] = u["decisions"][0]["why_short"]
    u["decisions"][0]["title"] = "Use the [KV cache](p1:kvcache)"
    u["question"] = "Does [this arm](x1:arms) hold?"
    return u


def test_inline_link_resolves_to_a_relative_page_by_default():
    page = render_page(_linked_unit(prereqs=[{"unit": "p1", "label": "LLM serving"}]))
    assert ('Built on the <a href="../p1/page.html#c-kvcache" target="_blank" '
            'rel="noopener">KV &lt;cache&gt;</a>, see <strong>this</strong>.') in page
    # a link to this unit's own concept stays on the page
    assert 'Does <a href="#c-arms">this arm</a> hold?' in page
    # an escaped-only field shows the link text
    assert '<h3>Use the KV cache</h3>' in page


def test_inline_link_uses_the_published_url_when_known():
    page = render_page(_linked_unit(links={"p1": "https://claude.ai/artifact/a\"b"}))
    assert ('<a href="https://claude.ai/artifact/a&quot;b#c-kvcache" target="_blank" '
            'rel="noopener">KV &lt;cache&gt;</a>') in page


def test_brief_writes_links_as_text():
    brief = render_brief(_linked_unit(prereqs=[{"unit": "p1", "label": "LLM serving"}]))
    assert "Built on the KV <cache> (P1: kvcache), see **this**." in brief
    assert "### Use the KV cache (P1: kvcache)" in brief
    assert "Read first: LLM serving (P1)." in brief


def test_unknown_unit_in_a_link_fails_to_render():
    u = artifact_unit()
    u["decisions"][0]["why"] = "See [x](p9:kvcache)."
    with pytest.raises(ContentError, match="p9"):
        render_page(u)
    with pytest.raises(ContentError, match="p9"):
        render_brief(u)


def test_resolve_does_not_change_the_input_and_inline_stays_stateless():
    u = _linked_unit(prereqs=[{"unit": "p1", "label": "LLM serving"}])
    before = repr(u)
    resolve_links(u, "page")
    assert repr(u) == before
    # a raw markdown link is not a link: only resolved unit links are
    assert "<a " not in inline("[x](https://evil.example) [y](javascript:alert(1))")


def test_read_first_banner_sits_under_the_title():
    page = render_page(_linked_unit(prereqs=[{"unit": "p1", "label": "LLM serving on a GPU"}],
                                    links={"p1": "https://claude.ai/artifact/p1"}))
    hero = page.split('<header class="hero">')[1].split("</header>")[0]
    banner = re.search(r'<div class="readfirst">(.*?)</div>', hero).group(1)
    assert banner == ('<b>Read first:</b> <a href="https://claude.ai/artifact/p1" '
                      'target="_blank" rel="noopener">LLM serving on a GPU</a>')
    assert hero.index("</h1>") < hero.index('class="readfirst"')
    assert 'class="readfirst"' not in render_page(artifact_unit())


# ---- small fixes ----

def test_sources_are_a_collapsed_details_with_a_count():
    page = render_page(artifact_unit())
    src = page.split('<section id="sources">')[1].split("</section>")[0]
    assert src.startswith('<details class="src"><summary>Sources, 1 file and section</summary>')
    assert "<details open" not in src and "docs/post.md" in src
    u = artifact_unit()
    u["sources"] = u["sources"] * 3
    assert "<summary>Sources, 3 files and sections</summary>" in render_page(u)


def test_requirement_grid_is_at_most_three_columns_of_at_least_300px():
    from study.page import CSS
    assert (".rgrid{grid-template-columns:repeat(auto-fill,"
            "minmax(min(100%,max(300px,calc((100% - 24px)/3))),1fr))}") in CSS
    why = render_page(artifact_unit_with_links()).split('<section id="why">')[1]
    assert why.split("</h2>")[1].startswith('<div class="grid rgrid">')


def _edge_labels(out):
    return [(float(m.group(1)), float(m.group(2)), m.group(3), m.group(4)) for m in re.finditer(
        r'<text class="elabel" x="([\d.-]+)" y="([\d.-]+)" text-anchor="(\w+)">([^<]*)<', out)]


def _edge_lines(out):
    return [tuple(float(v) for v in m.groups()) for m in re.finditer(
        r'<line class="edge" x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)"', out)]


def _view3(nodes, edge_label="writes results"):
    return {"level": "container", "title": "t", "caption": "c",
            "nodes": [{"id": k, "label": k, "col": c, "row": r} for k, c, r in nodes],
            "edges": [{"from": nodes[0][0], "to": nodes[1][0], "label": edge_label}]}


def test_horizontal_edge_label_sits_clearly_above_its_line():
    out = diagram_html(_view3([("a", 0, 0), ("b", 1, 0)]), "e0")
    (_, y1, _, _), = _edge_lines(out)
    for _x, y, anchor, _ in _edge_labels(out):
        assert anchor == "middle" and y <= y1 - 8


def test_vertical_edge_label_sits_beside_its_line():
    out = diagram_html(_view3([("a", 0, 0), ("b", 0, 1)]), "e1")
    (x1, y1, _, y2), = _edge_lines(out)
    for x, y, anchor, _ in _edge_labels(out):
        assert anchor == "start" and x >= x1 + 6
        assert min(y1, y2) < y < max(y1, y2) + 4


def test_diagonal_edge_label_is_offset_off_its_line():
    out = diagram_html(_view3([("a", 0, 0), ("b", 1, 1)], "a long label that wraps"), "e2")
    (x1, y1, x2, y2), = _edge_lines(out)
    import math
    for x, y, anchor, txt in _edge_labels(out):
        # the label's anchor point is at least 8 px from the line
        d = abs((y2 - y1) * x - (x2 - x1) * y + x2 * y1 - y2 * x1) / math.hypot(x2 - x1, y2 - y1)
        assert d >= 8, txt
        assert anchor in ("start", "end")


def test_c4_views_carry_a_one_line_legend_and_prereq_views_do_not():
    page = render_page(artifact_unit())
    legend = ("solid box: part of this system · dashed: outside it · bold: where this "
              "study&#x27;s key step happens")
    assert page.count(f'<p class="dlegend">{legend}</p>') == 4
    assert 'class="dlegend"' not in render_page(prereq_unit())
    from study.page import CSS
    assert ".dlegend{display:none}" in _media(CSS, "max-width:600px")


def test_interval_prints_the_precision_as_authored():
    rows = [{"label": "d", "estimate": -10.39, "low": -20.3, "high": -5.54}]
    out = chart_html(_interval(rows), "i8")
    for shown in (">−20.30<", ">−5.54<", ">−10.39 s<"):
        assert shown in out, shown
    rows = [{"label": "d", "estimate": -10.4, "low": -20.3, "high": -5.5}]
    assert ">−20.3<" in chart_html(_interval(rows), "i8")
    rows = [{"label": "d", "estimate": -10.4, "low": -20.3, "high": -5.5, "decimals": 2}]
    out = chart_html(_interval(rows), "i8")
    assert ">−20.30<" in out and ">−10.40 s<" in out and ">−5.50<" in out


def test_interval_shade_is_explained_under_the_axis():
    rows = [{"label": "d", "estimate": -10.39, "low": -20.3, "high": -5.54}]
    out = chart_html(dict(_interval(rows), shade="left"), "i9")
    assert ('<p class="cnote"><span class="shswatch"></span>shaded: the side where '
            'B faster</p>') in out.split("</svg>")[1]
    out = chart_html(dict(_interval(rows), shade="right", shade_caption="shaded: A **wins**"),
                     "i9")
    assert '<span class="shswatch"></span>shaded: A <strong>wins</strong></p>' in out
    assert "shaded" not in chart_html(_interval(rows), "i9")


def test_edge_label_moves_to_the_other_side_rather_than_under_a_box():
    # a -> b runs diagonally past c; c sits on the label's first-choice side (up and right)
    view = _view3([("a", 0, 0), ("b", 1, 2), ("c", 1, 1)], "cache state")
    out = diagram_html(view, "e3")
    rects = [(float(x), float(y)) for x, y in re.findall(r'<rect x="([\d.]+)" y="([\d.]+)"', out)]
    cx, cy = rects[2]  # node c
    for x, y, anchor, txt in _edge_labels(out):
        w = len(txt) * 6.2
        left = {"end": x - w, "middle": x - w / 2}.get(anchor, x)
        overlaps = left < cx + 170 and left + w > cx and y - 11 < cy + 72 and y + 3 > cy
        assert not overlaps, (x, y, anchor)
    # labels are drawn after the boxes, so a label that cannot avoid a box stays on top
    assert out.rindex('class="elabel"') > out.rindex('<g class="node')


# ---- canonical segment colours ----

def test_canonical_phases_have_one_colour_on_every_page():
    from study.svg import CANONICAL_SEGMENT_SLOTS, segment_slots
    page_a = segment_slots([_stacked("Platform (by subtraction)", "Compile", "First request")])
    page_b = segment_slots([_stacked("Weights", "Everything else: scratch space and the KV cache"),
                            _stacked("First request", "Server launch to model loaded", "Compile")])
    for slots in (page_a, page_b):
        for name, slot in slots.items():
            assert slot == CANONICAL_SEGMENT_SLOTS[name], name
    assert page_a["Compile"] == page_b["Compile"] == 1
    assert len({k for n, k in CANONICAL_SEGMENT_SLOTS.items()
                if not n.startswith("Everything else")}) == 8


def test_a_canonical_slot_that_collides_in_one_chart_falls_back_to_a_free_one():
    from study.svg import segment_slots
    chart = _stacked("Platform (by subtraction)",
                     "Everything else: scratch space and the KV cache",
                     "Server launch to model loaded")
    slots = segment_slots([chart])
    assert slots["Platform (by subtraction)"] == 2  # first come keeps the canonical slot
    assert slots["Server launch to model loaded"] == 0
    assert slots["Everything else: scratch space and the KV cache"] not in (0, 2)
    # without the clash, it keeps its canonical slot
    alone = segment_slots([_stacked("Weights", "Everything else: scratch space and the KV cache")])
    assert alone["Everything else: scratch space and the KV cache"] == 2


def test_unknown_names_avoid_the_slots_canonical_phases_take_on_the_page():
    from study.svg import segment_slots
    slots = segment_slots([_stacked("Mystery", "Compile"), _stacked("Server launch to model loaded")])
    assert slots == {"Compile": 1, "Server launch to model loaded": 0, "Mystery": 2}


def test_urls_in_links_are_not_scanned_for_numbers(tmp_path):
    src = _write(tmp_path, "post.md", "# Title\n")
    u = artifact_unit()
    u["results"] = []
    u["sources"] = [{"file": src, "section": "Title"}]
    u["links"] = {"p1": "https://claude.ai/artifact/ERS8Z3tRWUkSD4131zgwzY"}
    assert untraced_numbers(u) == []


# ---- implementation flow as a timeline ----

from tests.study_examples import artifact_unit_with_flow


def _flow(page):
    return page.split('<section id="flow">')[1].split("</section>")[0]


def _steps(flow):
    """Each step's <li> HTML, in page order."""
    return re.findall(r'<li class="fl-step[^"]*".*?</li>', flow, re.DOTALL)


def test_plain_flow_renders_exactly_as_before():
    flow = _flow(render_page(artifact_unit()))
    assert flow == ('<h2>Implementation flow</h2><div class="flow">'
                    + "".join(f'<div class="step"><b>Step {i}</b><div class="why">Detail {i}.'
                              "</div></div>" for i in range(3))
                    + "</div>")


def test_phased_flow_keeps_the_section_id_and_nav_pill():
    page = render_page(artifact_unit_with_flow())
    assert '<a href="#flow">Flow</a>' in page
    assert re.findall(r'<section id="([\w-]+)"', page).count("flow") == 1
    assert '<div class="flow">' not in page


def test_phases_are_bands_in_order_with_step_counts():
    flow = _flow(render_page(artifact_unit_with_flow()))
    bands = re.findall(r'<div class="fl-band">(.*?)</div>', flow, re.DOTALL)
    names = [re.search(r"<h3>(.*?)</h3>", b).group(1) for b in bands]
    assert names == ["Design", "Measure", "Analyse and publish"]
    counts = [re.search(r'<span class="fl-pc">(.*?)</span>', b).group(1) for b in bands]
    assert counts == ["2 steps", "3 steps", "3 steps"]
    assert "Phase 1 of 3" in bands[0] and "Phase 3 of 3" in bands[2]
    # every step sits inside its phase's list, numbered on across phases
    phases = flow.split('<div class="fl-phase">')[1:]
    assert [len(_steps(p)) for p in phases] == [2, 3, 3]
    nodes = re.findall(r'<span class="fl-node" aria-hidden="true">(\d+)</span>', flow)
    assert nodes == [str(i) for i in range(1, 9)]


def test_each_step_shows_label_detail_output_when_and_number():
    u = artifact_unit_with_flow()
    steps = _steps(_flow(render_page(u)))
    assert len(steps) == 8
    for i, (s, li) in enumerate(zip(u["flow"], steps, strict=True), 1):
        assert f'id="flow-s{i}"' in li
        assert f"<h4>{esc(s['label'])}</h4>" in li
        assert f'<div class="fl-detail">{esc(s["detail"])}</div>' in li
        assert f'<div class="fl-out"><b>Output:</b> {esc(s["output"])}</div>' in li
        assert f'<span class="fl-when">{esc(s["when"])}</span>' in li


def test_milestones_are_marked_and_only_milestones():
    u = artifact_unit_with_flow()
    steps = _steps(_flow(render_page(u)))
    for s, li in zip(u["flow"], steps, strict=True):
        ms = bool(s.get("milestone"))
        assert li.startswith('<li class="fl-step fl-ms"') == ms
        assert ('<span class="fl-tag">Milestone</span>' in li) == ms


def test_milestone_strip_links_each_milestone_with_its_date():
    page = render_page(artifact_unit_with_flow())
    flow = _flow(page)
    strip = flow.split('<ol class="fl-strip"')[1].split("</ol>")[0]
    items = re.findall(r'<a href="#(flow-s\d+)"><span class="fl-sdate">(.*?)</span>'
                       r'<span class="fl-slabel">(.*?)</span></a>', strip)
    assert items == [("flow-s2", "2026-08-28", "Pre-register the hypotheses and rules"),
                     ("flow-s4", "2026-09-02 to 09-04", "Run interleaved triples"),
                     ("flow-s8", "2026-09-12", "Publish what re-derives")]
    assert flow.index("fl-strip") < flow.index("fl-tl")
    assert "8 steps in 3 phases, 3 milestones" in flow


def test_decision_chip_uses_the_decision_code_and_links_to_its_card():
    page = render_page(artifact_unit_with_flow())
    steps = _steps(_flow(page))
    assert '<a class="fl-dec" href="#d-d1"><b>Decision D2</b> Decision 1</a>' in steps[1]
    assert '<a class="fl-dec" href="#d-d2"><b>Decision D3</b> Decision 2</a>' in steps[2]
    assert "fl-dec" not in steps[0]
    assert '<span class="code">D2</span>Decision 1' in page  # the card shows the same code


def test_evidence_is_plain_monospace_text_not_links():
    steps = _steps(_flow(render_page(artifact_unit_with_flow())))
    ev = steps[3].split('<div class="fl-ev">')[1].split("</div>")[0]
    assert ev == ('<b>Evidence</b> <code>abcdef0</code> store committed · '
                  '<code>0fedcba987</code> in ~/projects/other-repo, worker image pinned')
    assert "<a" not in ev
    assert "fl-ev" not in steps[4]  # no evidence, no line


def test_every_flow_link_lands_on_an_existing_unique_id():
    page = render_page(artifact_unit_with_flow())
    ids = re.findall(r' id="([^"]+)"', page)
    assert len(ids) == len(set(ids))
    for target in _hrefs(_flow(page)):
        assert target in ids, target


def test_flow_text_is_escaped():
    u = artifact_unit_with_flow()
    u["flow"][1].update(label="<b>x</b>", output="<i>o</i>", when="<w>")
    u["flow"][1]["evidence"][0]["note"] = "<n>"
    flow = _flow(render_page(u))
    for raw in ("<b>x</b>", "<i>o</i>", "<w>", "<n>"):
        assert raw not in flow


def test_timeline_css_is_two_columns_wide_and_one_column_on_phones():
    from study.page import CSS
    assert ".fl-step:not(:last-child):before" in CSS or ".fl-tl:before" in CSS
    wide = _media(CSS, "min-width:1100px")
    assert ".fl-card{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr)" in wide
    assert ".fl-card{display:grid" not in CSS.split("@media")[0]
    assert "overflow-wrap:anywhere" in CSS.split(".fl-ev{")[1].split("}")[0]


def _brief_flow(brief):
    return brief.split("## Implementation flow\n")[1].split("\n## ")[0]


def test_brief_plain_flow_is_unchanged():
    assert _brief_flow(render_brief(artifact_unit())) == (
        "\n1. **Step 0**: Detail 0.\n2. **Step 1**: Detail 1.\n3. **Step 2**: Detail 2.\n")


def test_brief_phased_flow_is_numbered_and_grouped_by_phase():
    flow = _brief_flow(render_brief(artifact_unit_with_flow()))
    lines = flow.splitlines()
    assert "8 steps in 3 phases, 3 milestones." in lines
    assert ("Milestones: 2. Pre-register the hypotheses and rules (2026-08-28); "
            "4. Run interleaved triples (2026-09-02 to 09-04); "
            "8. Publish what re-derives (2026-09-12).") in lines
    heads = [ln for ln in lines if ln.startswith("### ")]
    assert heads == ["### Phase 1 of 3: Design (2 steps)", "### Phase 2 of 3: Measure (3 steps)",
                     "### Phase 3 of 3: Analyse and publish (3 steps)"]
    numbered = [ln.split(".")[0] for ln in lines if re.match(r"\d+\. ", ln)]
    assert numbered == [str(i) for i in range(1, 9)]
    i = lines.index("2. **Pre-register the hypotheses and rules** [MILESTONE]: Hypotheses, "
                    "contrasts, stopping rules and the gate are committed before the first "
                    "paid run.")
    assert lines[i + 1:i + 5] == [
        "   - Output: a frozen pre-registration in docs/experiment.md",
        "   - When: 2026-08-28",
        "   - Decision: `d1` Decision 1",
        "   - Evidence: 5d6e7f8a9b",
    ]
    assert ("   - Evidence: abcdef0 (store committed); 0fedcba987 in ~/projects/other-repo "
            "(worker image pinned)") in lines
    assert sum("[MILESTONE]" in ln for ln in lines) == 3
    j = lines.index("5. **Store, never retry**: A failure is its own row: a retry would swap "
                    "unlucky runs for faster ones.")
    assert lines[j + 1:j + 3] == ["   - Output: failure rows kept next to the successes",
                                  "   - When: 2026-09-04"]
    assert not lines[j + 3].startswith("   - ")


# ---- flow evidence: not numeric claims, and every commit must exist ----

import subprocess

from study.trace import missing_commits


def test_evidence_shas_and_dates_are_not_numeric_claims(tmp_path):
    src = _write(tmp_path, "post.md", "# Title\nnothing numeric\n")
    u = artifact_unit_with_flow()
    u["results"] = []
    u["sources"] = [{"file": src, "section": "Title"}]
    u["flow"][1]["when"] = "14.09.2026"
    u["flow"][1]["evidence"] = [{"commit": "a123456", "note": "run 812 stored"}]
    u["flow"][1]["output"] = "a store of 812 rows"
    assert untraced_numbers(u) == ["812"]  # the output is a claim; the when and evidence are not


def _repo(tmp_path):
    repo = Path(tmp_path) / "repo"
    repo.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, env=env,
                              capture_output=True, text=True).stdout.strip()
    git("init", "-q")
    (repo / "f.txt").write_text("x\n")
    git("add", "f.txt")
    git("commit", "-q", "-m", "one")
    return repo, git("rev-parse", "HEAD"), git("rev-parse", "HEAD:f.txt")


def _cite(*evidence):
    u = artifact_unit_with_flow()
    for s in u["flow"]:
        s.pop("evidence", None)
    u["flow"][1]["evidence"] = list(evidence)
    return u


def test_missing_commits_finds_real_commits_and_flags_the_rest(tmp_path):
    repo, head, blob = _repo(tmp_path)
    u = _cite({"commit": head[:7]}, {"commit": head, "repo": str(repo)},
              {"commit": "deadbee"}, {"commit": blob, "repo": str(repo)})
    missing, unavailable = missing_commits(u, repo)
    assert missing == [f"deadbee in {repo}", f"{blob} in {repo}"]  # a blob is not a commit
    assert unavailable == []


def test_missing_commits_expands_the_home_tilde(tmp_path, monkeypatch):
    _, head, _ = _repo(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert missing_commits(_cite({"commit": head, "repo": "~/repo"}), Path("/")) == ([], [])


def test_missing_commits_reports_what_it_cannot_check(tmp_path, monkeypatch):
    repo, head, _ = _repo(tmp_path)
    plain = Path(tmp_path) / "plain"
    plain.mkdir()
    u = _cite({"commit": head, "repo": str(tmp_path / "gone")},
              {"commit": head, "repo": str(plain)}, {"commit": head})
    missing, unavailable = missing_commits(u, repo)
    assert missing == []
    assert unavailable == [f"{tmp_path / 'gone'}: no such directory",
                           f"{plain}: not a git repository"]
    monkeypatch.setattr("study.trace.shutil.which", lambda name: None)
    assert missing_commits(u, repo) == ([], ["git is not on PATH"])


# ---- trace: one registry of chart types ----

def test_every_chart_type_has_a_number_reader():
    from study.schema import CHART_TYPES
    from study.trace import CHART_NUMBERS
    assert set(CHART_NUMBERS) == set(CHART_TYPES)


def test_unknown_chart_type_is_a_content_error_naming_the_type(tmp_path):
    src = _write(tmp_path, "post.md", "# Title\n")
    u = artifact_unit()
    u["sources"] = [{"file": src, "section": "Title"}]
    u["results"][0]["chart"] = {"type": "radar", "unit": "s"}
    with pytest.raises(ContentError, match=r"results\[0\]\.chart: unknown chart type 'radar'"):
        untraced_numbers(u)


def test_large_chart_values_are_traced_without_an_exponent(tmp_path):
    src = _write(tmp_path, "post.md", "# Title\n1,234,567 tokens\n")
    u = artifact_unit()
    u["sources"] = [{"file": src, "section": "Title"}]
    u["results"][0]["chart"] = {"type": "bars", "unit": "tokens",
                                "items": [{"label": "a", "value": 1234567}]}
    assert untraced_numbers(u) == []


# ---- xy chart ----

import html
import itertools

from tests.study_examples import xy_chart


def _pts(out, cls="xym"):
    """(series class, px, py, title) for every marker."""
    return [(m.group(1), float(m.group(2)), float(m.group(3)), m.group(4)) for m in re.finditer(
        rf'<path class="{cls}[^"]*? (xk\d)[^"]*" data-px="([\d.-]+)" data-py="([\d.-]+)"'
        r'[^>]*><title>([^<]*)</title>', out)]


def _box(out):
    w, h = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', out).groups()
    return float(w), float(h)


def _xy_texts_inside(out):
    """Every text's estimated extent lies inside the viewBox."""
    width, height = _box(out)
    for cls, x, y, anchor, txt in _texts(out):
        w = len(html.unescape(txt)) * 8.5
        left = {"end": x - w, "middle": x - w / 2}.get(anchor, x)
        assert left >= -0.5 and left + w <= width + 0.5, txt
        assert y - 12 >= 0 and y + 3 <= height, txt


def test_xy_places_a_known_point_at_its_pixel():
    out = chart_html(xy_chart(), "x0")
    m = {(k, title.split(": ")[1].split(" ")[0]): (px, py) for k, px, py, title in _pts(out)}
    (x0, y0), (x50, y50), (x100, y100) = m[("xk0", "0")], m[("xk0", "50")], m[("xk0", "100")]
    assert abs(x50 - (x0 + x100) / 2) < 0.15 and abs(y50 - (y0 + y100) / 2) < 0.15
    assert x0 < x50 < x100 and y0 > y50 > y100  # y grows upwards
    # the x tick labelled 50 sits under the point at x = 50; the gridline for 10 at y = 10
    ticks = {t[4]: t[1] for t in _texts(out) if "xyt" in t[0] and t[3] == "middle"}
    assert abs(ticks["50"] - x50) < 0.15
    grid = {float(v): float(y) for v, y in re.findall(
        r'<line class="xygrid" data-v="([\d.-]+)" x1="[\d.]+" y1="([\d.]+)"', out)}
    assert abs(grid[10] - y100) < 0.15
    # the axis starts at zero by default: y = 0 is on the x axis line
    axis_y = float(re.search(r'<line class="xyaxis" x1="[\d.]+" y1="([\d.]+)" x2="[\d.]+" '
                             r'y2="\1"', out).group(1))
    assert abs(axis_y - y0) < 0.15


def test_xy_log_x_spaces_decades_evenly_and_ticks_them():
    c = xy_chart(x_log=True, series=[{"name": "a", "points": [
        {"x": 1, "y": 1}, {"x": 10, "y": 2}, {"x": 100, "y": 3}]}])
    out = chart_html(c, "x1")
    xs = [px for _, px, _, _ in _pts(out)]
    assert abs((xs[1] - xs[0]) - (xs[2] - xs[1])) < 0.15
    ticks = [t[4] for t in _texts(out) if "xyt" in t[0] and t[3] == "middle"]
    assert ticks[0] == "1" and "10" in ticks and ticks[-1] == "100"


def test_xy_log_x_of_powers_of_two_ticks_each_power():
    c = xy_chart(x_log=True, series=[{"name": "a", "points": [
        {"x": 2 ** k, "y": k} for k in range(8)]}])
    out = chart_html(c, "x2")
    ticks = [t for t in _texts(out) if "xyt" in t[0] and t[3] == "middle"]
    assert [t[4] for t in ticks] == ["1", "2", "4", "8", "16", "32", "64", "128"]
    gaps = [b[1] - a[1] for a, b in itertools.pairwise(ticks)]
    assert max(gaps) - min(gaps) < 0.3


def test_xy_band_spans_the_plot_between_its_values_behind_the_series():
    c = xy_chart(bands=[{"y_lo": 5, "y_hi": 10, "label": "tolerance"}])
    out = chart_html(c, "x3")
    pts = {title: (px, py) for _, px, py, title in _pts(out)}
    y5, y10 = pts["measured: 50 → 5 s"][1], pts["measured: 100 → 10 s"][1]
    x, y, w, h = map(float, re.search(r'<rect class="xyband" x="([\d.]+)" y="([\d.]+)" '
                                      r'width="([\d.]+)" height="([\d.]+)"', out).groups())
    assert abs(y - y10) < 0.15 and abs(y + h - y5) < 0.15
    axis = re.search(r'<line class="xyaxis" x1="([\d.]+)" y1="[\d.]+" x2="([\d.]+)"', out)
    assert abs(x - float(axis.group(1))) < 0.15 and abs(x + w - float(axis.group(2))) < 0.15
    assert out.index('class="xyband"') < out.index('class="xyl')
    assert ">tolerance<" in out


def test_xy_refs_are_dashed_lines_with_labels():
    c = xy_chart(refs=[{"y": 5, "label": "target"}, {"x": 50, "label": "cap"}])
    out = chart_html(c, "x4")
    pts = {title: (px, py) for _, px, py, title in _pts(out)}
    px50, py5 = pts["measured: 50 → 5 s"]
    refs = re.findall(r'<line class="xyref" x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" '
                      r'y2="([\d.]+)"', out)
    horiz = [r for r in refs if r[1] == r[3]]
    vert = [r for r in refs if r[0] == r[2]]
    assert abs(float(horiz[0][1]) - py5) < 0.15 and abs(float(vert[0][0]) - px50) < 0.15
    assert ">target<" in out and ">cap<" in out
    from study.page import CSS
    assert "stroke-dasharray" in CSS.split(".xyref{")[1].split("}")[0]


def test_xy_whisker_runs_from_lo_to_hi():
    out = chart_html(xy_chart(), "x5")
    pts = {title: (px, py) for _, px, py, title in _pts(out)}
    px, py = pts["model: 0 → 1 s (0.5 to 1.5)"]
    w = re.search(r'<line class="xyw xk1" x1="([\d.]+)" y1="([\d.]+)" x2="\1" y2="([\d.]+)"', out)
    assert abs(float(w.group(1)) - px) < 0.15
    lo_y, hi_y = float(w.group(2)), float(w.group(3))
    assert lo_y > py > hi_y and abs((lo_y - py) - (py - hi_y)) < 0.15


def test_xy_series_differ_in_colour_and_shape_and_have_a_legend():
    c = xy_chart(series=[{"name": f"s{k}", "points": [{"x": 0, "y": k}, {"x": 1, "y": k + 1}]}
                         for k in range(6)])
    out = chart_html(c, "x6")
    shapes = {}
    for m in re.finditer(r'<path class="xym (xk\d)" data-px="[\d.-]+" data-py="[\d.-]+" '
                         r'data-shape="([\w-]+)"', out):
        shapes.setdefault(m.group(1), set()).add(m.group(2))
    assert len(shapes) == 6 and len({s.pop() for s in shapes.values()}) == 6
    legend = out.split("</svg>", 1)[1]
    for k in range(6):
        assert f'class="xychip xk{k}"' in legend and f">s{k}</li>" in legend
    from study.page import CSS
    colours = [re.search(rf"\.xk{k}{{color:(var\(--c\d\))}}", CSS).group(1) for k in range(6)]
    assert len(set(colours)) == 6
    assert not re.search(r'(fill|stroke)="#', out)


def test_xy_one_series_needs_no_legend():
    out = chart_html(xy_chart(series=[xy_chart()["series"][0]]), "x7")
    assert 'class="legend' not in out


def test_xy_labels_the_last_value_of_each_series():
    out = chart_html(xy_chart(), "x8")
    values = [t[4] for t in _texts(out) if "xyv" in t[0]]
    assert sorted(values) == ["10", "8"]


def test_xy_line_and_step_paths():
    c = xy_chart()
    out = chart_html(c, "x9")
    assert re.search(r'<path class="xyl xk0" d="M[\d.]+ [\d.]+L[\d.]+ [\d.]+L', out)
    assert 'class="xyl xk1"' not in out  # a points series draws no line
    c["series"][0]["style"] = "step"
    out = chart_html(c, "x9")
    assert re.search(r'<path class="xyl xk0" d="M[\d.]+ [\d.]+H[\d.]+V[\d.]+H', out)


def test_xy_text_stays_inside_the_viewbox_and_readable_on_a_phone():
    for c in (xy_chart(), xy_chart(x_log=True, series=[{"name": "a", "points": [
            {"x": 1, "y": 0.284}, {"x": 128, "y": 0.6061}]}],
            refs=[{"x": 128, "label": "max-num-seqs, the engine's cap"},
                  {"y": 0.6, "label": "a long reference label here"}],
            bands=[{"y_lo": 0.2, "y_hi": 0.3, "label": "the band"}])):
        out = chart_html(c, "xa")
        _xy_texts_inside(out)
        width, _ = _box(out)
        assert width <= 420 and 309 / width * 15 >= 12


def test_xy_dual_axes_scale_the_right_series_on_its_own_ticks():
    c = xy_chart(y_axes="dual", y2_label="throughput", y2_unit="req/s")
    c["series"][1].update(axis="right", points=[{"x": 0, "y": 50}, {"x": 100, "y": 100}])
    out = chart_html(c, "xb")
    right = [t for t in _texts(out) if "xyt" in t[0] and t[3] == "start"]
    assert [t[4] for t in right] == ["0", "20", "40", "60", "80", "100"]
    pts = {title: (px, py) for _, px, py, title in _pts(out)}
    # 100 req/s is the right axis' top tick, at the same height as 10 s on the left
    assert abs(pts["model: 100 → 100 req/s"][1] - pts["measured: 100 → 10 s"][1]) < 0.15
    assert re.search(r'<path class="xym xk1 r"', out)  # hollow: right-axis marks
    assert "throughput (req/s)" in out and "latency (s)" in out
    assert "(right axis)" in out.split("</svg>", 1)[1]
    _xy_texts_inside(out)


def test_xy_aria_label_names_each_series_and_its_ranges():
    out = chart_html(xy_chart(refs=[{"y": 5, "label": "target"}]), "xc")
    label = re.search(r'aria-label="([^"]+)"', out).group(1)
    assert "measured: 3 points, x 0 to 100, y 0 to 10 s" in label
    assert "model: 2 points, x 0 to 100, y 1 to 8 s" in label
    assert "requests in flight" in label and "target at y = 5" in label


def test_xy_note_prints_under_the_chart():
    out = chart_html(xy_chart(note="Read **this**."), "xd")
    assert '<p class="cnote">Read <strong>this</strong>.</p>' in out


def test_brief_lists_xy_series_as_x_y_pairs():
    u = artifact_unit()
    u["results"][0]["chart"] = xy_chart(bands=[{"y_lo": 2, "y_hi": 4, "label": "tolerance"}],
                                        refs=[{"y": 5, "label": "target"}], note="A note.")
    brief = render_brief(u)
    assert "- Axes: x is requests in flight; y is latency (s)" in brief
    assert "- measured: 0: 0, 50: 5, 100: 10" in brief
    assert "- model (points): 0: 1 (0.5 to 1.5), 100: 8" in brief
    assert "- Band: tolerance, 2 to 4 s" in brief
    assert "- Reference: target at y = 5 s" in brief
    assert "- Note: A note." in brief


def test_xy_values_are_traced(tmp_path):
    src = _write(tmp_path, "post.md", "# Title\n0.284 0.606 1.5 128 0.25 0.75 2.5\n")
    u = artifact_unit()
    u["sources"] = [{"file": src, "section": "Title"}]
    u["results"][0]["chart"] = xy_chart(
        series=[{"name": "a", "points": [{"x": 1, "y": 0.284, "lo": 0.25, "hi": 0.75},
                                         {"x": 128, "y": 0.606}]}],
        bands=[{"y_lo": 0.25, "y_hi": 1.5, "label": "b"}], refs=[{"y": 2.5, "label": "r"}])
    assert untraced_numbers(u) == []
    ch = u["results"][0]["chart"]
    ch["bands"][0]["y_hi"] = 1.75
    ch["refs"] = [{"x": 3.5, "label": "r"}]
    ch["series"][0]["points"][0]["hi"] = 0.95
    ch["series"][0]["points"][1]["x"] = 256
    assert untraced_numbers(u) == ["0.95", "256", "1.75", "3.5"]
