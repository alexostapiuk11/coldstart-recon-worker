import importlib.util
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _build_module():
    """Import scripts/build_explainer.py as a module, for the branch tests.

    It is a script, not a package member, so there is no import path to it.
    The alternative -- asserting on the rendered SVG -- does not work for what
    these tests need to check: matplotlib emits label text as positioned glyph
    references rather than as characters, so no number printed on a chart is
    greppable in the output.
    """
    spec = importlib.util.spec_from_file_location(
        "_build_explainer", REPO / "scripts" / "build_explainer.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build(tmp_path):
    out = tmp_path / "index.html"
    r = subprocess.run(
        [sys.executable, "scripts/build_explainer.py", "--out", str(out)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    return out.read_text()


def test_build_leaves_no_unsubstituted_placeholders(tmp_path):
    html = _build(tmp_path)
    assert "{{" not in html, "a placeholder survived the build"


def test_build_substitutes_a_number_from_committed_data(tmp_path):
    html = _build(tmp_path)
    assert "39.4" in html  # arm C median, from analysis.json


def test_build_inlines_the_chart_as_svg_not_a_link(tmp_path):
    html = _build(tmp_path)
    assert "<svg" in html
    assert ".png" not in html


def test_build_knows_every_chart_the_page_asks_for(tmp_path):
    """Every `{{chart:name}}` on the page renders, and each gets its own SVG.

    The chart map is a chain of string comparisons, so a figure that exists in
    figures.py is still unreachable from the page until someone adds a branch
    for it. Counting placeholders against inlined `<svg` elements catches the
    missing branch (the build exits non-zero and `_build` asserts on that) and
    also catches a branch that renders nothing.
    """
    page = (REPO / "explainer" / "page.html").read_text()
    asked = re.findall(r"\{\{chart:([^}]+)\}\}", page)
    assert {"shortcut", "per_host"} <= set(asked), "Part II's charts left the page"
    html = _build(tmp_path)
    # +1 for the spine: inlined as an SVG, but hand-drawn rather than a chart.
    assert html.count("<svg") == len(asked) + 1


def test_shortcut_chart_is_drawn_from_this_campaigns_published_intervals(tmp_path):
    """The upper panel must carry the same endpoints the prose quotes.

    `shortcut_panels` draws whatever three intervals it is handed, including
    the constructed counter-example it uses for its lower panel. Wired to the
    wrong dict it would still render a plausible figure -- one showing the
    shortcut failing on a campaign where it worked, which is the precise claim
    an earlier draft got wrong. So assert on what the branch passes down.
    """
    from coldstart.explainer.numbers import resolve

    module = _build_module()
    charts = module._Charts(REPO, tmp_path)
    seen = {}

    def spy(intervals, out_path):
        seen.update(intervals)
        Path(out_path).write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
        return Path(out_path)

    from coldstart.analysis import figures

    original = figures.shortcut_panels
    figures.shortcut_panels = spy
    try:
        charts.render("shortcut")
    finally:
        figures.shortcut_panels = original

    for short, key in (
        ("ab", "contrast_ab_total"),
        ("bc", "contrast_bc_total"),
        ("diff", "difference_of_contrasts"),
    ):
        ci = resolve(key, repo=REPO)
        assert seen[short] == (ci["lo"], ci["hi"]), f"{short} panel is not the published interval"


def test_per_host_chart_is_drawn_from_every_run_not_the_gated_subset(tmp_path):
    """The figure's whole point is that all of the paid runs shared one host.

    Filtering the first-touch run out first would draw n=299 under a sentence
    saying 300, and the chart travels without that sentence.
    """
    module = _build_module()
    charts = module._Charts(REPO, tmp_path)
    seen = {}

    def spy(rows, out_path):
        seen["n"] = len(rows)
        Path(out_path).write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
        return Path(out_path)

    from coldstart.analysis import figures

    original = figures.per_host_medians
    figures.per_host_medians = spy
    try:
        charts.render("per_host")
    finally:
        figures.per_host_medians = original

    assert seen["n"] == len(charts.rows())


def test_build_inlines_the_spine_with_its_group_ids_intact(tmp_path):
    """The spine lives in its own file, but must reach the page inline.

    And it must arrive with its ids unchanged: the scroll choreography looks
    the zone and clock groups up by literal id, so an id-namespacing pass like
    the one charts get would leave a diagram that renders and never lights.
    """
    page = tmp_path / "page.html"
    # The diagram labels a vLLM step "size KV cache", so the page it lands in
    # owes that definition. Carrying it here keeps this test about inlining
    # rather than about the jargon gate -- but it is worth seeing that the gate
    # reaches into the spine at all.
    page.write_text(
        "<p>a KV cache is per-conversation scratch space the model keeps on the"
        " GPU while generating</p><div>{{spine}}</div>"
    )
    out = tmp_path / "spine.html"
    r = subprocess.run(
        [sys.executable, "scripts/build_explainer.py", "--page", str(page), "--out", str(out)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    html = out.read_text()
    assert '<svg id="spine"' in html
    for group in ("zone-1", "zone-7", "clock-A", "clock-C", "edge-1"):
        assert f'id="{group}"' in html, f"{group} did not survive the build"


def test_build_fails_loudly_on_an_unknown_placeholder(tmp_path):
    bad = REPO / "explainer" / "_bad.html"
    bad.write_text("{{not_a_key}}")
    try:
        r = subprocess.run(
            [
                sys.executable,
                "scripts/build_explainer.py",
                "--page",
                str(bad),
                "--out",
                str(tmp_path / "x.html"),
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        assert r.returncode != 0
        assert "not_a_key" in r.stderr
    finally:
        bad.unlink()


def test_build_escapes_html_special_characters_in_a_code_excerpt(tmp_path):
    """An excerpt carrying `<` must reach the page as `&lt;`, not as markup.

    The default page's excerpt happens to contain no HTML-special character,
    so without this the escaping is never exercised and could be dropped
    without a single test turning red. `checks-rtt-floor` has both `<` and `>`.
    """
    page = tmp_path / "page.html"
    page.write_text("<pre><code>{{excerpt:checks-rtt-floor}}</code></pre>")
    out = tmp_path / "escaped.html"
    r = subprocess.run(
        [sys.executable, "scripts/build_explainer.py", "--page", str(page), "--out", str(out)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    html = out.read_text()
    assert "&lt;" in html
    body = html[len("<pre><code>") : -len("</code></pre>")]
    assert "<" not in body, "an unescaped angle bracket would be parsed as a tag"
